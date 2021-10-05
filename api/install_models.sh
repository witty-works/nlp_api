#!/bin/sh

cd data || exit;

if [ ! -d "./en_core_web_trf-3.0.0/en_core_web_trf/en_core_web_trf-3.0.0" ]; then
  wget https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.0.0/en_core_web_trf-3.0.0.tar.gz
  tar -xf en_core_web_trf-3.0.0.tar.gz
  rm -rf en_core_web_trf-3.0.0.tar.gz
fi

if [ ! -d "./de_dep_news_trf-3.0.0/de_dep_news_trf/de_dep_news_trf-3.0.0" ]; then
  wget https://github.com/explosion/spacy-models/releases/download/de_dep_news_trf-3.0.0/de_dep_news_trf-3.0.0.tar.gz
  tar -xf de_dep_news_trf-3.0.0.tar.gz
  rm -rf de_dep_news_trf-3.0.0.tar.gz
fi
