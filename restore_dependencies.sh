du -sh $PLATFORM_CACHE_DIR
mkdir -p $HOME/.global
mkdir -p $HOME/.venv
mkdir -p $HOME/.pdm
mkdir -p $PLATFORM_CACHE_DIR/.global 
mkdir -p $PLATFORM_CACHE_DIR/.venv
mkdir -p $PLATFORM_CACHE_DIR/.pdm

echo "Restoring from  build cache"
rsync -ar $PLATFORM_CACHE_DIR/.venv/ $HOME/.venv
rsync -ar $PLATFORM_CACHE_DIR/.global/ $HOME/.global
rsync -ar $PLATFORM_CACHE_DIR/.pdm/ $HOME/.pdm
echo "Done restoring from build cache"