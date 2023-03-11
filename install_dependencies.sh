du -sh $PLATFORM_CACHE_DIR
mkdir -p $HOME/.global
mkdir -p $HOME/.venv
mkdir -p $HOME/.pdm
mkdir -p $PLATFORM_CACHE_DIR/.global 
mkdir -p $PLATFORM_CACHE_DIR/.venv
mkdir -p $PLATFORM_CACHE_DIR/.pdm

echo "Restoring from build cache"
rsync -ar $PLATFORM_CACHE_DIR/.venv/ $HOME/.venv
rsync -ar $PLATFORM_CACHE_DIR/.global/ $HOME/.global
rsync -ar $PLATFORM_CACHE_DIR/.pdm/ $HOME/.pdm
echo "Done restoring from build cache"

echo "Installing pdm"
pip install pdm
pdm config install.cache True
pdm config cache_dir $HOME/.pdm
pdm run python -m ensurepip

echo "Installing pdm dependencies"
pdm sync --prod

echo "Saving to build cache"
rsync -ar $HOME/.venv/ $PLATFORM_CACHE_DIR/.venv
rsync -ar $HOME/.global/ $PLATFORM_CACHE_DIR/.global
rsync -ar $HOME/.pdm/ $PLATFORM_CACHE_DIR/.pdm
echo "Done saving to build cache"