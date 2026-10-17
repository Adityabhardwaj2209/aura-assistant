# AURA — Personal AI Assistant

**Talk, remember, research, plan, and learn from one local workspace.**

AURA is a modular personal assistant built with **Python, FastAPI, JavaScript, and SQLite**. It combines voice conversations, persistent goals and memory, document research, task planning, learning tools, controlled desktop actions, and an animated 3D robot avatar.

Developed by [Aditya Bhardwaj](https://github.com/Adityabhardwaj2209).

## Repository status

This repository contains the consolidated AURA source export, including the workspace upgrade, virtual body, perception modules, regression tests, and example quiz. Follow the fresh-clone instructions below; the separate upgrade ZIP and `install_workspace.py` are not required for this checkout.

> AURA is a software prototype. Its virtual body and organ-inspired services are simulations. Physical hardware integration is on hold. It does not claim consciousness, biological emotions, universal knowledge, or human-level autonomy.

## Features

| Area | What AURA provides |
| --- | --- |
| Voice and chat | Browser microphone input, model-based replies, Windows speech, saved conversation history, and interruption controls |
| Goal memory | Projects, goals, next actions, due dates, and unfinished tasks that persist across restarts |
| Daily dashboard | Goals, pending plans, recent documents, local files, and connection status |
| Task planning | AI-assisted decomposition, editable steps, saved checkpoints, manual confirmation, failure review, and explicit resume |
| Document workspace | PDF/TXT/MD import, cited excerpts, selected-document summaries and comparisons, and document-based quizzes |
| Web research | Explicit research routing through supported provider search tools, with source links when returned |
| Screen understanding | Analysis of screenshots explicitly chosen and submitted by the user |
| Desktop tools | Allowlisted Notepad/Calculator launch and file tools restricted to `workspace_files` |
| Offline tools | Local memory, file actions, document excerpts, saved quizzes, syntax checks, and reviewed tests; AI replies through an already installed Ollama model |
| 3D avatar | Procedural full-body joint rig with idle, wave, walk, and dance animations; Windows voice visemes when available |
| Coding assistant | AI diagnosis, Python syntax checks, reviewed unit tests, patch diffs, explicit apply, and hash-guarded rollback |
| Learning | Topic/document MCQs, saved quiz practice, answer explanations, attempt history, and weak-topic tracking |
| Memory controls | Inspect, correct, export, and delete workspace goals and facts |
| Performance | Workspace model latency, failures, returned token usage, and imported camera evaluation comparisons |
| Virtual body and camera | Simulated motion, organ-inspired service signals, browser object detection/tracking, and manually annotated camera evaluation |

## Architecture

The browser communicates with a FastAPI server bound to `127.0.0.1:8511`. Authenticated local endpoints connect the workspace, document library, conversation router, virtual body, and perception services.

- **Conversation layer:** voice/chat UI, tool routing, provider requests, and response recovery.
- **Knowledge layer:** SQLite document storage, keyword retrieval, and optional semantic embeddings.
- **Workspace layer:** persistent goals/facts, checkpointed plans, quizzes, coding tools, and request telemetry.
- **Presentation layer:** JavaScript dashboards, Three.js avatar, and virtual-body rendering.
- **Control layer:** allowlisted local actions, fixed known software repairs, and explicit user actions.

Cloud AI requests use your configured provider session. The local model adapter connects only to Ollama on loopback. Desktop tools and virtual animation do not imply physical robot control.

## Quick start — Windows CMD

### 1. Clone the repository

```cmd
git clone https://github.com/Adityabhardwaj2209/aura-assistant.git
cd aura-assistant
```

### 2. Create the environment and install dependencies

Use a supported Python installation. Automated tests for this export were run with Python 3.12; the existing user deployment has also been used with Python 3.14, but this export has not been independently verified on that Windows runtime.

```cmd
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

These are commands for you to run. The launcher does not install packages or download a local AI model. Dependencies are not locked to a reproducible release yet.

Optional semantic document retrieval:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements-semantic.txt
```

Semantic indexing can download its embedding model when explicitly invoked. Keyword retrieval remains available if the optional embedding dependency/model is unavailable.

### 3. Start AURA

```cmd
start_aura_workspace.cmd
```

Open **http://127.0.0.1:8511/workspace**. Keep the CMD window open. Stop the current server with **Ctrl+C** before starting another instance.

### 4. Configure AI access

Open **Voice & chat**, enter your own Groq API key, and save settings. The key is kept in the current server session; restarting requires entering it again. Never commit keys, screenshots containing keys, or personal databases.

For local AI replies, start an already installed Ollama instance, choose **Local Ollama** in the workspace, click **Check local models**, and enter an installed model's exact name. AURA does not automatically install Ollama or pull a model.

## Pages

| URL path | Purpose |
| --- | --- |
| `/workspace` | Dashboard, goals/memory, planner, documents, learning, coding, screen analysis, avatar, and performance |
| `/` | Existing voice/chat interface |
| `/brain` | Import, search, and delete local documents |
| `/body` | Virtual body, organ-inspired signals, camera tracking, and evaluation |

The workspace avatar is generated procedurally. The older chat page's separate avatar viewer optionally expects your own `selected_avatar.glb`, which is not included. Its absence does not prevent the workspace or chat text from working.

## Try it

1. Save a goal and fact in **Goals & memory**, restart AURA, and verify they remain.
2. Create a plan with two manual steps. Advance, confirm a step, restart, and resume.
3. Import two documents through `/brain`, refresh the workspace, and generate cited excerpts or an AI comparison.
4. Import `examples/quiz.json`, answer the questions, and inspect topic performance.
5. Create `demo.py` under **Desktop & files**, then load it in **Coding**:

   ```python
   def add(a, b):
       return a + b
   ```

6. Run a syntax check, review the supplied unit-test example, and explicitly enable test execution. Propose a change, inspect its diff, apply it, and try rollback.
7. Open **Avatar & speech**, choose a gesture, and try a short spoken message. The UI reports whether real voice visemes or amplitude fallback are active.
8. Choose a harmless screenshot, inspect its preview, and click **Send screenshot & analyze**.

## Tests

Core offline checks:

```cmd
.venv\Scripts\python.exe check_aura.py
.venv\Scripts\python.exe -m unittest test_workspace -v
```

If Node.js is already installed:

```cmd
node test_body_js.js
node test_perception_js.js
node test_eval_js.js
node test_workspace_js.js
node test_worklet_js.js
```

The source export includes **54 workspace Python fixture tests**, **11 workspace JavaScript fixture/static checks**, **3 audio-worklet checks**, and the existing AURA regression suites. Fixture tests do not establish actual camera accuracy or real provider/Windows behavior. See [validation notes](docs/VALIDATION_REPORT.txt).

Optional checks:

```cmd
.venv\Scripts\python.exe check_aura.py --server
```

Use `--server` only while AURA is already running. The separate `--model` option may load/download the existing embedding model; it is not required for the offline suite.

## Data and privacy

- Workspace records are stored in `brain_data/workspace.db`; documents and chat have separate local SQLite databases.
- Local desktop file tools operate inside `workspace_files`.
- Cloud AI requests can include the prompt, relevant workspace goals/facts, and selected document excerpts. Explicit screenshot analysis sends the selected image to the configured cloud vision model.
- Screenshot files are not saved by the new analysis endpoint. Camera detection runs in the browser; the perception API accepts detection metadata rather than image frames.
- Workspace export can contain quiz solutions and patch source backups. Handle exports as personal files.
- `.gitignore` excludes databases, credentials, uploaded files, generated media, model caches, local workspaces, and backups. None of those are bundled in this source export.

## Execution boundaries and limitations

- **Reviewed tests are not a security sandbox.** They run in a separate Python process and temporary working folder with your account permissions. The main process has a 15-second timeout and capped output, but this does not constrain every child process that reviewed code might create. Review code and tests before running them.
- File creation and patch application require explicit actions. Stale patches and rollback refuse to overwrite later edits. Self-care handles fixed known repair recipes, not arbitrary autonomous software rewrites.
- Plans advance one bounded step per explicit request. Restart does not automatically replay an interrupted step.
- Document summaries/comparisons use selected excerpts, with coverage shown; scanned PDFs require separate OCR.
- Generated quizzes can contain mistakes and are not official GATE or placement papers.
- Avatar and detection models/scripts need network access on first load. Windows speech depends on installed System.Speech voices; mouth sync falls back when a voice emits no visemes.
- Telemetry covers the new workspace's AI operations, not every historical provider request or billing charge. Unknown token usage remains unknown.
- The virtual body's walking/dance are animations/simulations, not validated biomechanics or hardware locomotion.

## Project layout

| Files | Responsibility |
| --- | --- |
| `phase3_web.py`, `run_aura*.py` | Local server and launch lifecycle |
| `aura_router.py`, `aura_followup.py`, `aura_reliability.py` | Routing, context, and request recovery |
| `aura_brain.py`, `aura_semantic.py`, `brain_routes.py` | Documents and retrieval |
| `aura_heart.py`, `aura_emotions.py`, `aura_selfcare.py` | Response styles and known repairs |
| `aura_workspace_*.py` | Goals, plans, AI adapters, tools, quizzes, metrics, and speech timing |
| `workspace.*`, `workspace_avatar.js` | Workspace frontend and avatar |
| `aura_body*.py`, `aura_organs.py`, `body_*.js` | Virtual body and service signals |
| `aura_perception*.py`, `perception_*.js` | Detection metadata and tracking |
| `eval_*.js` | Camera evaluation and report export |
| `test_*.py`, `test_*_js.js` | Offline regression and fixture tests |
| `docs/`, `examples/` | Detailed walkthrough, validation notes, and example quiz |

## Roadmap

- Pin and verify dependencies in a reproducible Windows build.
- Add automated browser and Windows speech integration tests.
- Improve full-document coverage and retrieval evaluation.
- Add stronger OS-level isolation before expanding untrusted-code execution.
- Collect representative, consented camera evaluation data.
- Resume physical hardware integration only when hardware is available.

Detailed workspace instructions: [WORKSPACE_GUIDE.txt](docs/WORKSPACE_GUIDE.txt).
