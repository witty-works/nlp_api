"""Application startup and lifecycle management."""

import os
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.context import AppContext
from app.db import Db
from app.models import LangType, WordType
from app.http import Http
from app.nouns import Nouns
from app.verbs import Verbs
from app.adjectives import Adjectives
from app.alternatives import Alternatives
from app.languagetool import LanguageTool
from app.prompt import Prompt
from app.llm_alternatives import LlmAlternatives
from app.rule_check import RuleCheck
from app.regex_check import RegexCheck
from app.emoji_check import EmojiCheck
from app.config_manager import parse_term_replacements


@asynccontextmanager
async def lifespan(app: FastAPI, context: AppContext):
    # Startup
    # Expose context on FastAPI app.state for DI-friendly access
    app.state.context = context
    if os.environ.get("BLACKFIRE_ENABLE_CONTINUOUS_PROFILING"):
        try:
            from blackfire_conprof.profiler import Profiler

            app_name = os.environ.get("PLATFORM_APPLICATION_NAME")
            profiler = Profiler(application_name=app_name)
            profiler.start()

            print(f"Profiler started for {app_name}")
        except Exception:
            pass

    # Initialize HTTP client
    context.http = Http(context.settings, context.logger)

    # Configure SQLite logging
    sqlite_logger = logging.getLogger("aiosqlite")
    sqlite_logger.setLevel(logging.WARNING)

    # Initialize database
    context.db = await Db.factory(context.settings, context.languages)
    context.model.db = context.db
    context.model.ambiguous_number_lookup = (
        await context.db.fetch_ambiguous_number_forms()
    )
    context.model.de_verb_surface_forms = await context.db.fetch_surface_forms(
        LangType.DE, WordType.VERB
    )
    context.model.de_noun_surface_forms = await context.db.fetch_surface_forms(
        LangType.DE, WordType.NOUN
    )

    # Canned user and organisation records for the test suite, which
    # authenticates as the email they carry. They are fixtures, not
    # configuration: an entry marked "force" in one overrides what a request
    # asks for, so a deployment that loaded them would silently answer with
    # something other than what its clients requested. Only under TESTING.
    if context.settings.testing_rules and not context.settings.testing:
        context.logger.error(
            "TESTING_RULES is set but TESTING is not, so it will be ignored. "
            "Use DEFAULT_CONFIG and DEFAULT_API_KEY for a real deployment."
        )

    if context.settings.testing and context.settings.testing_rules:
        rules = json.loads(context.settings.testing_rules)

        rules["term_replacements"] = parse_term_replacements(
            rules["term_replacements"], context
        )
        email = rules["email"]
        context.redis.db.set(context.redis.get_user_id(email), json.dumps(rules))

    if context.settings.testing and context.settings.testing_organization_rules:
        organization_rules = json.loads(context.settings.testing_organization_rules)

        organization_rules["term_replacements"] = parse_term_replacements(
            organization_rules["term_replacements"], context
        )
        key = organization_rules["id"]
        context.redis.db.set(key, json.dumps(organization_rules))

    if context.settings.redis_log_emails:
        log_emails = json.loads(context.settings.redis_log_emails)
        for email in log_emails:
            context.redis.db.lpush("debug_emails", email)

    # Initialize language processors
    context.nouns = Nouns(
        context.settings,
        context.logger,
        context.static_rules,
        context.model,
        context.db,
    )
    context.verbs = Verbs(
        context.settings,
        context.logger,
        context.static_rules,
        context.model,
        context.db,
    )
    context.adjectives = Adjectives(context.settings, context.logger, context.db)
    context.alternatives = Alternatives(
        context.settings,
        context.logger,
        context.static_rules,
        context.db,
        context.model,
        context.nouns,
        context.verbs,
        context.adjectives,
    )
    context.languagetool = LanguageTool(
        context.settings,
        context.logger,
        context.static_rules,
        context.db,
        context.categories,
        context.http,
    )
    context.prompt = Prompt(context.settings)
    context.llm_alternatives = LlmAlternatives(
        context.settings, context.alternatives, context.prompt
    )
    context.rule_check = RuleCheck(
        context.settings,
        context.logger,
        context.static_rules,
        context.model,
        context.db,
        context.nouns,
        context.verbs,
        context.adjectives,
        context.alternatives,
    )
    context.regex_check = RegexCheck(
        context.settings, context.logger, context.static_rules, context.nouns
    )
    context.emoji_check = EmojiCheck(
        context.settings, context.logger, context.static_rules
    )

    yield

    # Shutdown
    await context.http.close()
    await context.db.close()
    # Clean up reference on app.state
    if hasattr(app.state, "context"):
        delattr(app.state, "context")
