# M1: Compiler Tuning Harness

You are implementing Milestone M1 for the Glasshouse project. Read these files first:
- ARCHITECTURE.md (sections 2, 4 for backend layout and contract schema)
- TODO.md (M1 section for detailed tasks)
- SPEC.md (section 3 for the four Compiler verification passes)

## Environment
- Use conda environment `glasshouse` (Python 3.10): `conda activate glasshouse`
- All Python work goes in `backend/` directory

## Goal
Build an isolated eval script to iterate on the Blind Compiler's system prompt. Establish a baseline for violation detection.

## Tasks
1. Initialize Python project in `backend/` with `pyproject.toml` and `requirements.txt`
2. Install in the conda env: `pip install openai anthropic instructor pydantic pytest pytest-cov`
3. Create `app/logger.py` - structured JSON logging with DEBUG mode
4. Create `app/prompts/compiler.md` - Blind Compiler system prompt with:
   - Explicit: "You have NOT seen the user's original prompt"
   - Define four verification passes
   - 2-3 few-shot examples
5. Create `app/schemas.py` - Pydantic models for Contract, Violation, CompilerOutput
6. Create `app/llm.py` - thin wrapper using `instructor` with temperature=0
7. Create `scripts/seed_contracts/` with 6-10 test contracts:
   - valid_simple.json, orphaned_node.json, missing_payload.json
   - silent_db_choice.json, unhandled_failure.json, intent_mismatch.json
8. Create `scripts/eval_compiler.py` - eval harness
9. Create `tests/conftest.py` and `tests/test_schemas.py`

## Acceptance Criteria
- `python scripts/eval_compiler.py` runs without errors
- Recall ≥ 80%, Precision ≥ 90%
- `valid_simple.json` passes with 0 violations
- Each invalid contract triggers expected violations
- `pytest tests/test_schemas.py` passes

## Key Schema Details
See ARCHITECTURE.md section 4 for full schema. The CompilerOutput should include:
- verdict: "pass" | "fail"
- violations: list with type, severity, message, affects, suggested_question
- questions: list of strings (max 5)
- intent_guess: string

Create commits as you complete major pieces.
