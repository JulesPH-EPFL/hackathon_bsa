import hashlib
import json
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

from qiskit import QuantumCircuit
from qiskit.qasm2 import loads as qasm2_loads
try:
    from qiskit.qasm2 import dump as _qasm2_dump
    import io as _io
    def _circuit_to_qasm(circuit) -> str:
        buf = _io.StringIO()
        _qasm2_dump(circuit, buf)
        return buf.getvalue()
except ImportError:
    def _circuit_to_qasm(circuit) -> str:
        return circuit.qasm()
from qiskit_aer import AerSimulator
from qiskit.compiler import transpile

try:
    from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler
    IBM_AVAILABLE = True
except ImportError:
    IBM_AVAILABLE = False

import src.config2 as config2

logger = logging.getLogger(__name__)


# ─── Résultat d'un job ────────────────────────────────────────────────────────

@dataclass
class QuantumResult:
    job_id:        str
    backend:       str
    shots:         int
    counts:        dict[str, int]   
    quasi_dists:   dict[str, float]      
    execution_time: float                
    result_hash:   str                   
    circuit_hash:  str                   
    timestamp:     float = field(default_factory=time.time)
    error:         Optional[str] = None
    success:       bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    def canonical_hash(self) -> str:
        """Hash déterministe du résultat — utilisé pour l'oracle trustless."""
        payload = json.dumps({
            "job_id":      self.job_id,
            "counts":      dict(sorted(self.counts.items())),
            "shots":       self.shots,
            "circuit_hash": self.circuit_hash,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


def _circuit_hash(qasm: str) -> str:
    return hashlib.sha256(qasm.strip().encode()).hexdigest()


def _counts_to_quasi(counts: dict, shots: int) -> dict:
    return {k: v / shots for k, v in counts.items()}


# ─── Simulateur local ─────────────────────────────────────────────────────────

def run_on_simulator(circuit: QuantumCircuit, shots: int, job_id: str) -> QuantumResult:
    qasm_str = _circuit_to_qasm(circuit)
    c_hash   = _circuit_hash(qasm_str)

    logger.info(f"[{job_id}] Simulateur local — {shots} shots, {circuit.num_qubits} qubits")
    t0 = time.perf_counter()

    simulator  = AerSimulator()
    transpiled = transpile(circuit, simulator)
    job        = simulator.run(transpiled, shots=shots)
    result     = job.result()
    counts     = result.get_counts()

    elapsed = time.perf_counter() - t0

    r_hash = hashlib.sha256(
        json.dumps(dict(sorted(counts.items())), sort_keys=True).encode()
    ).hexdigest()

    return QuantumResult(
        job_id        = job_id,
        backend       = "aer_simulator",
        shots         = shots,
        counts        = counts,
        quasi_dists   = _counts_to_quasi(counts, shots),
        execution_time = elapsed,
        result_hash   = r_hash,
        circuit_hash  = c_hash,
    )


# ─── IBM Quantum réel ─────────────────────────────────────────────────────────

def run_on_ibm(circuit: QuantumCircuit, shots: int, job_id: str) -> QuantumResult:
    if not IBM_AVAILABLE:
        raise RuntimeError("qiskit_ibm_runtime non installé — utilisez le simulateur.")
    if not config2.IBM_TOKEN:
        raise RuntimeError("IBM_QUANTUM_TOKEN manquant dans .env")

    qasm_str = _circuit_to_qasm(circuit)
    c_hash   = _circuit_hash(qasm_str)

    service = QiskitRuntimeService(
        channel  = "ibm_quantum",
        token    = config2.IBM_TOKEN,
        instance = config2.IBM_INSTANCE,
    )
    backend    = service.backend(config2.IBM_BACKEND)
    transpiled = transpile(circuit, backend)

    logger.info(f"[{job_id}] IBM backend={config2.IBM_BACKEND} — {shots} shots")
    t0 = time.perf_counter()

    sampler = Sampler(backend)
    job_ibm = sampler.run([transpiled], shots=shots)
    result  = job_ibm.result()
    elapsed = time.perf_counter() - t0

    pub_result = result[0]
    bitarray   = pub_result.data.meas
    counts: dict[str, int] = {}
    for bitstring in bitarray.get_bitstrings():
        counts[bitstring] = counts.get(bitstring, 0) + 1

    r_hash = hashlib.sha256(
        json.dumps(dict(sorted(counts.items())), sort_keys=True).encode()
    ).hexdigest()

    return QuantumResult(
        job_id         = job_id,
        backend        = config2.IBM_BACKEND,
        shots          = shots,
        counts         = counts,
        quasi_dists    = _counts_to_quasi(counts, shots),
        execution_time = elapsed,
        result_hash    = r_hash,
        circuit_hash   = c_hash,
    )


# ─── Point d'entrée principal ─────────────────────────────────────────────────

def execute_job(qasm: str, shots: int, job_id: str) -> QuantumResult:
    
    shots = min(shots, config2.MAX_SHOTS)

    try:
        circuit = qasm2_loads(qasm)
    except Exception as e:
        logger.error(f"[{job_id}] Circuit QASM invalide : {e}")
        return QuantumResult(
            job_id="", backend="", shots=0, counts={}, quasi_dists={},
            execution_time=0, result_hash="", circuit_hash="",
            error=str(e), success=False
        )

    try:
        if config2.USE_SIMULATOR:
            return run_on_simulator(circuit, shots, job_id)
        else:
            return run_on_ibm(circuit, shots, job_id)
    except Exception as e:
        logger.error(f"[{job_id}] Erreur d'exécution : {e}")
        return QuantumResult(
            job_id=job_id, backend="error", shots=shots, counts={},
            quasi_dists={}, execution_time=0, result_hash="", circuit_hash="",
            error=str(e), success=False
        )