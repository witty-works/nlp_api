FROM erikvl87/languagetool:5.5

# Become root user for file copying etc
USER root

# Add server properties
COPY --chown=languagetool server.properties /LanguageTool

# Add our own entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PORT 8000
EXPOSE 8000

USER languagetool

CMD [ "bash", "/entrypoint.sh" ]
