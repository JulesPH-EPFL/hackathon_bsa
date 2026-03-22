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
    from qiskit_ibm_runtime import Session
    IBM_AVAILABLE = True
except ImportError:
    IBM_AVAILABLE = False

import config

logger = logging.getLogger(__name__)


# ─── Résultat d'un job ────────────────────────────────────────────────────────

@dataclass
class QuantumResult:
    job_id:         str
    backend:        str
    shots:          int
    counts:         dict
    quasi_dists:    dict
    execution_time: float
    result_hash:    str
    circuit_hash:   str
    timestamp:      float = field(default_factory=time.time)
    error:          Optional[str] = None
    success:        bool = True
    # Champs IBM — remplis seulement en mode IBM réel
    ibm_job_id:     str = ""   # ID du job sur IBM Quantum (vérifiable)
    ibm_backend:    str = ""   # nom du backend IBM utilisé
    ibm_timestamp:  str = ""   # timestamp de fin du job IBM

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    def canonical_hash(self) -> str:
        payload = json.dumps({
            "job_id":       self.job_id,
            "counts":       dict(sorted(self.counts.items())),
            "shots":        self.shots,
            "circuit_hash": self.circuit_hash,
            "ibm_job_id":   self.ibm_job_id,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def ibm_verification_url(self) -> str:
        """URL publique pour vérifier le job sur IBM Quantum."""
        if self.ibm_job_id:
            return f"https://quantum.ibm.com/jobs/{self.ibm_job_id}"
        return ""


def _circuit_hash(qasm: str) -> str:
    return hashlib.sha256(qasm.strip().encode()).hexdigest()


def _counts_to_quasi(counts: dict, shots: int) -> dict:
    return {k: v / shots for k, v in counts.items()}


# ─── Vérification IBM ─────────────────────────────────────────────────────────

def verify_ibm_job(ibm_job_id: str, expected_counts: dict) -> dict:
    """
    Vérifie qu'un job IBM a bien été exécuté en le récupérant depuis l'API IBM.
    
    Retourne :
      {
        "verified": True/False,
        "status": "DONE" / "ERROR" / ...,
        "backend": "ibm_nairobi",
        "counts_match": True/False,
        "message": "..."
      }
    """
    if not IBM_AVAILABLE:
        return {"verified": False, "message": "qiskit_ibm_runtime non installé"}
    if not config.IBM_TOKEN:
        return {"verified": False, "message": "IBM_QUANTUM_TOKEN manquant dans .env"}
    if not ibm_job_id:
        return {"verified": False, "message": "Pas de ibm_job_id à vérifier"}

    try:
        service = QiskitRuntimeService(
            channel  = "ibm_cloud",
            token    = config.IBM_TOKEN,
            instance = config.IBM_INSTANCE,
        )
        job    = service.job(ibm_job_id)
        status = job.status().name   # DONE, RUNNING, ERROR, etc.

        if status != "DONE":
            return {
                "verified":     False,
                "status":       status,
                "message":      f"Job IBM non terminé : {status}",
                "ibm_job_id":   ibm_job_id,
            }

        # Récupérer les counts depuis IBM et comparer
        result = job.result()
        pub    = result[0]
        bitarray = pub.data.meas
        ibm_counts: dict[str, int] = {}
        for bs in bitarray.get_bitstrings():
            ibm_counts[bs] = ibm_counts.get(bs, 0) + 1

        # Comparer avec les counts reçus (tolérance 5% par état)
        counts_match = True
        total = sum(ibm_counts.values())
        for state, count in expected_counts.items():
            ibm_count = ibm_counts.get(state, 0)
            diff = abs(ibm_count - count) / max(total, 1)
            if diff > 0.05:
                counts_match = False
                break

        return {
            "verified":     status == "DONE" and counts_match,
            "status":       status,
            "backend":      job.backend().name,
            "counts_match": counts_match,
            "ibm_counts":   ibm_counts,
            "ibm_job_id":   ibm_job_id,
            "message":      "Job IBM vérifié avec succès" if counts_match else "Counts divergent",
        }

    except Exception as e:
        return {
            "verified": False,
            "message":  f"Erreur vérification IBM : {e}",
            "ibm_job_id": ibm_job_id,
        }


# ─── Simulateur local ─────────────────────────────────────────────────────────

def run_on_simulator(circuit: QuantumCircuit, shots: int, job_id: str) -> QuantumResult:
    qasm_str = _circuit_to_qasm(circuit)
    c_hash   = _circuit_hash(qasm_str)

    logger.info(f"[{job_id}] Simulateur local — {shots} shots, {circuit.num_qubits} qubits")
    t0 = time.perf_counter()

    sim        = AerSimulator()
    transpiled = transpile(circuit, sim)
    job        = sim.run(transpiled, shots=shots)
    result     = job.result()
    counts     = result.get_counts()
    elapsed    = time.perf_counter() - t0

    r_hash = hashlib.sha256(
        json.dumps(dict(sorted(counts.items())), sort_keys=True).encode()
    ).hexdigest()

    return QuantumResult(
        job_id         = job_id,
        backend        = "aer_simulator",
        shots          = shots,
        counts         = counts,
        quasi_dists    = _counts_to_quasi(counts, shots),
        execution_time = elapsed,
        result_hash    = r_hash,
        circuit_hash   = c_hash,
    )


# ─── IBM Quantum réel ─────────────────────────────────────────────────────────

def run_on_ibm(circuit: QuantumCircuit, shots: int, job_id: str) -> QuantumResult:
    if not IBM_AVAILABLE:
        raise RuntimeError("qiskit_ibm_runtime non installé")
    if not config.IBM_TOKEN:
        raise RuntimeError("IBM_QUANTUM_TOKEN manquant dans .env")

    qasm_str = _circuit_to_qasm(circuit)
    c_hash   = _circuit_hash(qasm_str)

    service = QiskitRuntimeService(
        channel  = "ibm_cloud",  # IBM Cloud
        token    = config.IBM_TOKEN,
        instance = config.IBM_INSTANCE,     # CRN de ton instance
    )
    backend    = service.backend(config.IBM_BACKEND)
    transpiled = transpile(circuit, backend)

    logger.info(f"[{job_id}] IBM backend={config.IBM_BACKEND} — {shots} shots")
    t0 = time.perf_counter()

    # Plan Open IBM — pas de Session, Sampler direct
    sampler = Sampler(backend=backend)
    ibm_job = sampler.run([transpiled], shots=shots)
    logger.info(f"[{job_id}] IBM Job ID : {ibm_job.job_id()}")
    result  = ibm_job.result()

    elapsed = time.perf_counter() - t0

    pub_result = result[0]
    bitarray   = pub_result.data.meas
    counts: dict[str, int] = {}
    for bs in bitarray.get_bitstrings():
        counts[bs] = counts.get(bs, 0) + 1

    r_hash = hashlib.sha256(
        json.dumps(dict(sorted(counts.items())), sort_keys=True).encode()
    ).hexdigest()

    ibm_finish_time = ibm_job.metrics().get("timestamps", {}).get("finished", "")

    logger.info(f"[{job_id}] IBM terminé — {elapsed:.2f}s — job_id IBM : {ibm_job.job_id()}")

    return QuantumResult(
        job_id         = job_id,
        backend        = config.IBM_BACKEND,
        shots          = shots,
        counts         = counts,
        quasi_dists    = _counts_to_quasi(counts, shots),
        execution_time = elapsed,
        result_hash    = r_hash,
        circuit_hash   = c_hash,
        ibm_job_id     = ibm_job.job_id(),
        ibm_backend    = backend.name,
        ibm_timestamp  = ibm_finish_time,
    )


# ─── Point d'entrée ───────────────────────────────────────────────────────────

def execute_job(qasm: str, shots: int, job_id: str) -> QuantumResult:
    shots = min(shots, config.MAX_SHOTS)

    try:
        circuit = qasm2_loads(qasm)
    except Exception as e:
        logger.error(f"[{job_id}] QASM invalide : {e}")
        return QuantumResult(
            job_id="", backend="", shots=0, counts={}, quasi_dists={},
            execution_time=0, result_hash="", circuit_hash="",
            error=str(e), success=False
        )

    try:
        if config.USE_SIMULATOR:
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