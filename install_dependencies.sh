du -sh $PLATFORM_CACHE_DIR
mkdir -p $HOME/.global
mkdir -p $HOME/.venv
mkdir -p $PLATFORM_CACHE_DIR/.global 
mkdir -p $PLATFORM_CACHE_DIR/.venv
mkdir -p __pypackages__
echo "Restoring from  build cache"
rsync -ar $PLATFORM_CACHE_DIR/.venv/ $HOME/.venv
rsync -ar $PLATFORM_CACHE_DIR/.global/ $HOME/.global
echo "Done restoring from build cache"

echo "Installing pdm and pdm dependecies"
pip install pdm --user
pdm config install.cache True
pdm config cache_dir $PLATFORM_CACHE_DIR/pdm
pdm run python -m ensurepip
pdm sync --prod

echo "Saving to build cache"
rsync -ar $HOME/.venv/ $PLATFORM_CACHE_DIR/.venv
rsync -ar $HOME/.global/ $PLATFORM_CACHE_DIR/.global
echo "Done saving to build cache"