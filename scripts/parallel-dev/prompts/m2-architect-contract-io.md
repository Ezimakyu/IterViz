# M2: Architect Agent + Contract I/O

You are implementing Milestone M2 for the Glasshouse project. Read these files first:
- ARCHITECTURE.md (sections 2, 3, 4 for backend layout, API surface, contract schema)
- TODO.md (M2 section for detailed tasks)
- SPEC.md (sections 1, 2 for the Architect's role)

## Environment
- Use conda environment `glasshouse` (Python 3.10): `conda activate glasshouse`
- All Python work goes in `backend/` directory
- Install deps: `pip install fastapi uvicorn openai anthropic instructor pydantic pytest pytest-cov httpx`

## Goal
Implement the Architect agent that converts user prompts into valid contracts, and persist contracts to SQLite.

## Tasks
1. Create `app/prompts/architect.md` - Architect system prompt with:
   - Input: user prompt + optional previous contract + user answers
   - Output: full Contract JSON
   - 2-3 few-shot examples
2. Create `app/architect.py`:
   - `generate_contract(prompt: str) -> Contract`
   - `refine_contract(contract: Contract, answers: list[Decision]) -> Contract`
   - Use `instructor` with response_model=Contract
3. Create `app/contract.py`:
   - SQLite table: sessions (id, created_at, contract_json, status)
   - CRUD functions: create_session, get_session, update_contract
   - JSON schema validation on every write
4. Create `app/api.py` with FastAPI routes:
   - `POST /api/v1/sessions` - create session, call Architect
   - `GET /api/v1/sessions/{id}` - return current contract
5. Create `app/main.py`:
   - FastAPI app factory
   - CORS middleware (allow localhost:5173)
   - Request logging middleware
6. Create tests: `test_contract.py`, `test_architect.py`, `test_api.py`

## Acceptance Criteria
- `pytest tests/ -v` passes
- `uvicorn app.main:app --reload` starts server
- `POST /sessions` with prompt returns valid Contract JSON
- Contract has ≥ 3 nodes, ≥ 2 edges
- `GET /sessions/{id}` returns same contract
- `DEBUG=1` shows LLM call timing in logs

## API Response Format
See ARCHITECTURE.md section 3.1 for endpoint specifications.

Create commits as you complete major pieces.
