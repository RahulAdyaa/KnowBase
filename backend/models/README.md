# Models (git-ignored)

GGUF model files are **not** committed to the repo. Download them locally:

```bash
cd backend/models
# Default: Qwen3-4B-Instruct Q4_K_M (~2.5 GB)
curl -L -o Qwen3-4B-Q4_K_M.gguf \
  https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf
```

Set `LOCAL_MODEL_PATH` in your `.env` (see `infra/.env.example`) to point at the file.
