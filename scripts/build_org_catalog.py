"""Build config/orgs.json from the public GitHub organizations.

Run this when the organizations add or rename repositories:

    python scripts/build_org_catalog.py

An optional GITHUB_TOKEN raises the unauthenticated API rate limit.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config" / "orgs.json"

ORG_DEFINITIONS = {
    "aossie": {
        "display_name": "AOSSIE",
        "github_org": "AOSSIE-Org",
        "website": "https://aossie.org",
        "description": "Australian Open Source Software Innovation and Education",
        "timezone": "Australia/Melbourne",
        "default_repo": "Info",
    },
    "stability": {
        "display_name": "Stability Nexus",
        "github_org": "StabilityNexus",
        "website": "https://stability.nexus",
        "description": "Open-source research and software for stable, transparent finance.",
        "timezone": "UTC",
        "default_repo": "Info",
    },
}

STOPWORDS = {
    "about", "after", "also", "among", "and", "another", "any", "app", "application",
    "apps", "are", "based", "been", "before", "being", "between", "build", "built",
    "can", "code", "component", "could", "data", "designed", "does", "each", "easy",
    "for", "from", "full", "has", "have", "help", "helps", "into", "its", "learn",
    "library", "local", "make", "more", "most", "new", "not", "open", "open-source",
    "opensource", "other", "our", "platform", "project", "projects", "provides",
    "repository", "server", "software", "source", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "through", "tool", "tools", "using",
    "very", "was", "website", "were", "what", "when", "where", "which", "while",
    "will", "with", "without", "your", "you", "users", "user", "support", "system",
    "based", "simple", "minimal", "modern", "official", "smart", "advanced",
}

ALIASES = {
    "aossie": {
        "SkillBot": ["skill bot", "skills bot", "discord assistant", "knowledge gaps"],
        "Gitcord-GithubDiscordBot": ["gitcord", "github discord", "discord github", "role sync"],
        "Resonate": ["resonate", "voice chat", "clubhouse"],
        "OpenVerifiableLLM": ["open verifiable llm", "verifiable llm", "open weight", "open-weight"],
        "BabyNest": ["babynest", "baby nest", "pregnancy"],
        "ThruBox-Server": ["thrubox", "thru box", "relay server"],
        "ThruBox-Client": ["thrubox client", "thru box client"],
        "CarbonTracker": ["carbon tracker", "co2", "carbon footprint"],
        "CarbonTracker-WatchCompanionApp": ["carbon tracker watch", "watch companion"],
        "DebateAI": ["debate ai", "debateai"],
        "Zplit": ["zplit", "split payment", "payment splitting"],
        "PictoPy": ["pictopy", "picto py", "photo gallery", "image gallery"],
        "Devr.AI": ["devr", "devr.ai", "devrel", "developer relations"],
        "InPactAI": ["inpact", "inpactai", "influencer"],
        "PullRequestDashboard": ["pull request dashboard", "pr dashboard", "merge dashboard"],
        "OrgExplorer": ["org explorer", "organization dashboard"],
        "WebSift": ["websift", "web sift"],
        "CodingAgent": ["coding agent", "ai coding"],
        "DocPilot": ["docpilot", "doc pilot", "emr"],
        "Monumento": ["monumento", "landmark", "ar"],
        "MoveYourBody": ["move your body", "fitness app"],
        "Info": ["aossie info", "contributor guidelines", "org info"],
        "Skills": ["aossie skills", "agent skills", "engineering rules"],
        "Website": ["aossie website", "official website"],
        "Gitcord-Test": ["gitcord test"],
    },
    "stability": {
        "Gluon-EVM": ["gluon evm", "gluon solidity", "stablecoin"],
        "Gluon-EVM-WebUI": ["gluon web ui", "gluon frontend"],
        "Gluon-Ergo-Contracts": ["gluon ergo", "gluon contracts"],
        "Gluon-Ergo-UI": ["gluon ergo ui"],
        "Gluon-LandingPage": ["gluon landing page", "gluon website"],
        "Gluon-Formalization-Coq": ["gluon formalization", "gluon coq"],
        "Gluon-PyGluon-Simulator": ["gluon simulator", "pygluon"],
        "Windmill-EVM-Contracts": ["windmill contracts", "windmill exchange", "auction exchange"],
        "Windmill-EVM-WebUI": ["windmill web ui", "windmill frontend"],
        "Windmill-EVM-Keeper": ["windmill keeper"],
        "Fate-EVM-Frontend": ["fate evm", "prediction pools"],
        "Fate-Solana": ["fate solana"],
        "Fate-Sui-Frontend": ["fate sui"],
        "OrbOracle-Solidity": ["orb oracle", "orboracle", "orb"],
        "OrbOracle-EVM-Frontend": ["orb oracle frontend"],
        "OrbOracle-Formalization": ["orb oracle formalization"],
        "Karma-EVM-Contracts": ["karma contracts"],
        "Karma-EVM-Frontend": ["karma frontend"],
        "Bene-FundRaising-EVM-Contracts": ["bene", "fundraising contracts"],
        "Bene-FundRaising-EVM-Frontend": ["bene frontend", "fundraising platform"],
        "BenefactionPlatform-Ergo": ["benefaction", "bene ergo"],
        "hodlCoin-Website": ["hodlcoin website", "hodl coin"],
        "hodlCoin-Solidity-WebUI": ["hodlcoin web ui", "hodlcoin staking"],
        "hodlcoin-Ergo-Frontend": ["hodlcoin ergo"],
        "IdentityTokens-EVM-Contracts": ["identity tokens", "identity token contracts"],
        "IdentityTokens-EVM-Frontend": ["identity tokens frontend"],
        "GitPay": ["gitpay", "git pay", "payout action"],
        "Chainvoice": ["chainvoice", "chain voice", "invoicing"],
        "MiniChain": ["minichain", "mini chain"],
        "Treee": ["treee", "tree planting", "tree nft"],
        "Tectonic-EVM-WebUI": ["tectonic", "tectonic web ui"],
        "VouchMe": ["vouchme", "vouch me"],
        "RainDrop-Solidity": ["raindrop contracts", "rain drop"],
        "RainDrop-Frontend": ["raindrop frontend"],
        "HackHub-Solidity": ["hackhub contracts", "hack hub"],
        "HackHub-WebUI": ["hackhub web ui"],
        "HammerAuctionHouse-Solidity": ["hammer auction", "auction house"],
        "HammerAuctionHouse-WebUI": ["hammer auction ui"],
        "Bountiful-BountyPlatform-Ergo": ["bountiful", "bounty platform"],
        "WalletLink": ["walletlink", "wallet link"],
        "TokenList": ["token list", "supported tokens"],
        "Info": ["stability nexus info", "org info"],
        "Papers": ["papers", "research papers"],
        "Website": ["stability nexus website", "official website"],
        "HackNexus": ["hacknexus", "hack nexus", "hackathon"],
        "StabilityWorkshop": ["stability workshop", "workshop"],
        "GoogleSummerOfCode": ["gsoc", "google summer of code"],
        "GSoC": ["gsoc", "google summer of code"],
        "Clowder": ["clowder"],
        "Plaza": ["plaza"],
    },
}


def fetch_json(url: str) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "aossie-frontdesk-catalog",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def tokens(value: str) -> list[str]:
    parts = re.findall(r"[a-z0-9]+", value.casefold())
    result: list[str] = []
    for part in parts:
        if len(part) < 3 or part in STOPWORDS:
            continue
        if part not in result:
            result.append(part)
    return result


def build_org(key: str, definition: dict) -> dict:
    github_org = definition["github_org"]
    repos_raw = fetch_json(f"https://api.github.com/orgs/{github_org}/repos?per_page=100&sort=updated")
    repos: dict[str, dict] = {}
    for repo in repos_raw:
        if repo.get("archived"):
            continue
        description = (repo.get("description") or "").strip()
        if description.casefold().startswith("mirror of"):
            continue
        name = repo["name"]
        keywords = tokens(name) + tokens(description)
        for alias in ALIASES.get(key, {}).get(name, []):
            alias_tokens = tokens(alias)
            if alias_tokens and alias.casefold() not in keywords:
                keywords.append(alias.casefold())
            for token in alias_tokens:
                if token not in keywords:
                    keywords.append(token)
        repos[name] = {
            "url": repo["html_url"],
            "description": description,
            "default_branch": repo.get("default_branch") or "main",
            "docs": ["README.md", "CONTRIBUTING.md"],
            "keywords": keywords[:40],
        }
    return {
        **definition,
        "catalogued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repos": dict(sorted(repos.items(), key=lambda item: item[0].casefold())),
    }


def main() -> None:
    catalog = {key: build_org(key, definition) for key, definition in ORG_DEFINITIONS.items()}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = {key: len(value["repos"]) for key, value in catalog.items()}
    print(f"Wrote {OUTPUT} with {counts}")


if __name__ == "__main__":
    main()
