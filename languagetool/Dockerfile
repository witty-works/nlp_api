FROM erikvl87/languagetool:5.5

# Become root user for file copying etc
USER root

RUN apk add --update make
RUN apk add --update git
RUN apk add --update clang
RUN apk add --update py3-numpy
RUN apk add --update py3-scipy
RUN apk add build-base
RUN git clone https://github.com/facebookresearch/fastText.git
WORKDIR fastText
RUN make
WORKDIR ..
RUN ls

# Add server properties
COPY --chown=languagetool server.properties /LanguageTool

#Add fasttext model
COPY --chown=languagetool lid.176.ftz /LanguageTool

# Add our own entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PORT 8000
EXPOSE 8000

# the percentage of heap size to use for languagetool
ENV HEAP_PERCENTAGE 80 

USER languagetool

CMD [ "bash", "/entrypoint.sh" ]
