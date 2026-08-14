# NextGen Memory

NextGen Memory is an experimental **Memory-MoE Kernel** for long-horizon LLM agents.

The system is designed to be:

- **eidetic at storage**: source evidence is append-only and preserved;
- **selective at recall**: a sparse router activates only the memory experts needed for the current task;
- **temporal and auditable**: event time, knowledge time, provenance, conflicts, state transitions, and retrieval outcomes are explicit;
- **self-improving**: successful and harmful retrievals become supervision for future routing and consolidation;
- **software-engineering aware**: execution state, repository structure, failures, recoveries, and validated skills are first-class memory types.

## Architecture

Neon/Postgres is the canonical ledger and control plane. MongoDB Atlas stores rich episodic, research, and repository payloads. A deterministic router is implemented first; learned routing is introduced only after trustworthy outcome telemetry exists.

## Status

The research direction and initial data substrate are established. The repository is being bootstrapped with reproducible migrations, typed routing contracts, tests, and project-continuity checkpoints.

See `docs/superpowers/specs/` for the approved design and `docs/superpowers/plans/` for the implementation plan.
