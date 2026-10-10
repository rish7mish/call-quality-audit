# Step 1: Turn call recordings into text (Sarvam)

**Goal:** convert call recordings into text with timestamps and speaker labels. Later steps grade these
transcripts and compare them with the auditors' verdicts.

**Time:** about 10 minutes of setup, then roughly 1–2 minutes per batch of 20 calls.

**Easiest way (Windows):** double-click `RUN_ME_transcribe.bat` and follow the window. It installs what it needs,
asks for the Sarvam key, tests 3 calls, and then runs the rest. The manual steps are below.

---

## You need
- This project folder, with the `.mp3` recordings in `audited_recordings\`
- A **Sarvam API key** from dashboard.sarvam.ai → API keys
- Python 3.10 or newer

## 1. Check Python
Open PowerShell and run:
```
python --version
```
If you get an error, install Python from python.org. During the install, **tick "Add python.exe to PATH"**, then
close and reopen PowerShell.

## 2. Open PowerShell inside the project folder
In File Explorer, open the project folder, click the address bar, type `powershell` and press Enter.

## 3. Install the Sarvam library (one time)
```
pip install sarvamai
```

## 4. Set the API key (every new PowerShell window)
```
$env:SARVAM_API_KEY = "paste-the-key-here"
```
Never put the key inside the script or send it in chat.

## 5. Test on 3 calls first
```
python transcribe_sarvam.py --limit 3
```
Then open the `transcripts\text\` folder and open one .txt file. It should look like:
```
[00:00] S0: Namaste, main IndiaMART se bol rahi hoon...
[00:03] S1: haan boliye
[00:11] S0: Aapko kitne piece chahiye?
```
Check:
- Are there two speakers (S0 and S1)? One is the bot, the other is the buyer.
- Is the Hindi/English readable?

If the text looks bad, try a different setting on the same 3 calls. Delete the 3 files in `transcripts\text\`
first, so the script redoes them:
```
python transcribe_sarvam.py --limit 3 --mode translit
```
(`translit` writes everything in English letters. The default `codemix` keeps Hinglish as spoken.)

## 6. Run all calls
```
python transcribe_sarvam.py
```
It prints a line as each batch of 20 finishes. When it ends, it says how many calls succeeded and failed.

**If some failed**, run the same command again. Finished calls are skipped.

## What gets created
| Path | What it is |
|---|---|
| `transcripts\text\<call>.txt` | Readable conversation, one line per turn |
| `transcripts\json\<call>.json` | Raw Sarvam output. Keep it; later steps use it |
| `transcripts\summary.csv` | One row per call: number of turns, speakers, longest silence, errors |

## Errors you might see
| Message | Fix |
|---|---|
| `SARVAM_API_KEY is not set` | Do step 4 again in this PowerShell window |
| `401` / `403` / `invalid key` | The key is wrong or has no credits; check the dashboard |
| `429` / `rate limit` | Too many batches at once. Run with `--workers 1` |
| `model` error | Run with `--model saaras:v3` |
| `pip is not recognized` | Python isn't on PATH; reinstall and tick "Add to PATH" |

## Data rule
Recordings and transcripts stay on your machine. They are excluded from the repo by `.gitignore`; don't upload
them to GitHub, Drive or chat tools.
