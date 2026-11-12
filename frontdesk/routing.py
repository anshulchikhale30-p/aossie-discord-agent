"""Repository routing for the two organization catalogs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import OrgDefinition, RepoDefinition
from .text import GENERIC_REPO_WORDS, token_set, tokenize

SKIP_REPOS = {
    ".github",
    "admin",
    "ContributorAutomation",
    "Gitcord-Test",
    "Template-Repo",
    "Template-Repo-NextJS",
    "Template-Repo-Flutter",
    "Template-Repo-EVM-Contracts",
    "Template-Repo-EVM-Keeper",
    "MCP-Template",
    "BenefactionPlatform-Ergo-Temporary",
    "Gluon-Ergo-Contracts-Old-To-Be-Deleted",
}


@dataclass(frozen=True)
class RepoRoute:
    name: str
    url: str
    description: str
    default_branch: str
    docs: tuple[str, ...]
    score: float = 0.0
    matched_terms: tuple[str, ...] = ()
    general: bool = False

    @property
    def display_name(self) -> str:
        return self.name


def _normalized_name(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", name.casefold()))


def _keyword_score(keyword: str, query_norm: str, query_terms: set[str]) -> float:
    keyword_norm = " ".join(keyword.casefold().split())
    if not keyword_norm:
        return 0.0
    if " " in keyword_norm:
        return 4.0 if keyword_norm in query_norm else 0.0
    if keyword_norm in query_terms:
        return 1.5 if keyword_norm in GENERIC_REPO_WORDS else 3.0
    return 0.0


def score_repo(repo: RepoDefinition, query: str) -> tuple[float, tuple[str, ...]]:
    query_norm = " ".join(query.casefold().split())
    query_terms = token_set(query)
    name_norm = _normalized_name(repo.name)
    name_terms = token_set(repo.name)
    matched: list[str] = []
    score = 0.0

    if name_norm and name_norm in query_norm:
        score += 12.0
        matched.append(repo.name)
    for term in name_terms:
        if term in query_terms:
            if term in GENERIC_REPO_WORDS:
                score += 1.0
            else:
                score += 4.0
                matched.append(term)
    for keyword in repo.keywords:
        value = _keyword_score(keyword, query_norm, query_terms)
        if value:
            score += value
            if " " in keyword:
                matched.append(keyword)
    description_terms = token_set(repo.description)
    overlap = query_terms & description_terms
    score += 0.75 * len(overlap)
    if overlap:
        matched.extend(sorted(overlap))
    # Avoid a generic word such as "app" routing to an arbitrary repo.
    if not name_terms & query_terms and not any(" " in value for value in matched):
        score *= 0.65
    return score, tuple(dict.fromkeys(matched))


def route_question(org: OrgDefinition, question: str, limit: int = 3) -> list[RepoRoute]:
    candidates: list[RepoRoute] = []
    for repo in org.repos.values():
        if repo.name in SKIP_REPOS:
            continue
        score, matched = score_repo(repo, question)
        if score <= 0:
            continue
        candidates.append(
            RepoRoute(
                name=repo.name,
                url=repo.url,
                description=repo.description,
                default_branch=repo.default_branch,
                docs=repo.docs,
                score=score,
                matched_terms=matched,
            )
        )
    candidates.sort(key=lambda route: (-route.score, len(route.name), route.name.casefold()))
    top = candidates[:limit]
    default_repo = org.repos.get(org.default_repo)
    if default_repo and not any(route.name == default_repo.name for route in top):
        top.append(
            RepoRoute(
                name=default_repo.name,
                url=default_repo.url,
                description=default_repo.description,
                default_branch=default_repo.default_branch,
                docs=default_repo.docs,
                score=0.0,
                general=True,
            )
        )
    if not top:
        return []
    # A weak keyword-only match should not outrank the organization's own
    # general information. Keep the default repo as a fallback context.
    return top


def best_route(org: OrgDefinition, question: str) -> RepoRoute | None:
    routes = route_question(org, question, limit=1)
    return routes[0] if routes else None


def route_names(routes: list[RepoRoute]) -> list[str]:
    return [route.name for route in routes if not route.general]
