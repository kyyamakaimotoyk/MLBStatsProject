# Model tuning log

Append-only experiment journal (the NBA project's `docs/model_tuning_log.md`
convention, which made every result auditable). Every model or feature change
gets an entry before it ships:

- **Hypothesis** — what should improve and why
- **Setup** — feature_set_version, model type(s), train/test windows
- **Result** — walk-forward metrics vs. the current baseline
- **Significance** — output of the noise-aware ablation harness
  (seeds × bootstrap × paired tests)
- **Decision** — ship / park behind a feature flag / reject

---
