echo "Installing pdm"
pip install pdm
pdm run python -m ensurepip

echo "Installing dependencies using pdm"
pdm sync --prod
ls -al $PLATFORM_CACHE_DIR
pdm cache clear
ls -al $PLATFORM_CACHE_DIR