"""Dev entrypoint: `python run.py` from the wiki/ directory."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8010, reload=True)
