"""Download SetFit models from Hugging Face Hub.

This script downloads pre-converted CPU models for the context checker from
Hugging Face Hub. Models are cached locally to avoid re-downloading.

Usage:
    uv run python -m bin.download_from_huggingface --lang en
    uv run python -m bin.download_from_huggingface --lang all
"""

import os
import shutil
import sys

import click
from huggingface_hub import snapshot_download

# The commit of witty-works/setfit-context-checker to download, so that every
# deployment runs the same model weights. Move it only with a reviewed change:
# new weights can change which findings the context checker keeps.
REVISION = "b8557691da55ab05c44f17b9b972d0c86e143f03"


@click.command()
@click.option(
    "--lang",
    "-l",
    default="all",
    help="Language to download (en, de, fr, or all). The repository has "
    "models for en and de; all skips a language it has no model for.",
)
@click.option(
    "--repo-id",
    default="witty-works/setfit-context-checker",
    help="Hugging Face repository ID",
)
@click.option(
    "--revision",
    default=REVISION,
    show_default=True,
    help="Commit of the repository to download",
)
def download(lang, repo_id, revision):
    """Download SetFit models from Hugging Face Hub."""
    languages = ["en", "de", "fr"] if lang == "all" else [lang]
    failed = False

    for language in languages:
        print(f"\n{'='*50}")
        print(f"Downloading {language} model from Hugging Face...")
        print(f"{'='*50}")

        try:
            # Download to local cache, then copy to our models directory
            cache_dir = snapshot_download(
                repo_id=repo_id,
                allow_patterns=f"{language}/*",
                cache_dir=".cache/huggingface",
                revision=revision,
            )

            source_dir = os.path.join(cache_dir, language)
            if not os.path.isdir(source_dir):
                print(f"- no {language} model in {repo_id} at {revision}, skipped")
                failed = failed or lang != "all"
                continue

            # Copied, not linked: compose.yml mounts only ./models into the
            # container, where a link into the download cache points nowhere.
            # copytree follows the cache's own links to the blobs.
            target_dir = f"models/context_aware_model/{language}"
            os.makedirs("models/context_aware_model", exist_ok=True)

            # lexists: a symlink left pointing at nothing is replaced too.
            if os.path.lexists(target_dir):
                print(f"Removing existing {target_dir}")
                if os.path.islink(target_dir):
                    os.unlink(target_dir)
                else:
                    shutil.rmtree(target_dir)

            shutil.copytree(source_dir, target_dir)
            print(f"✓ {language} model ready at {target_dir}")

        except Exception as e:
            print(f"✗ Failed to download {language} model: {e}")
            failed = True
            continue

    print(f"\n{'='*50}")
    print("Download complete!")
    print(f"{'='*50}")
    print("\nEnable models by setting: CONTEXT_CHECKER_LOCAL=true")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    download()
