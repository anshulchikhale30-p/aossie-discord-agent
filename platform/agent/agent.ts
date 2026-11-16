import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { defineAgent } from "eve";

/**
 * Use an OpenAI-compatible endpoint (vLLM, Ollama, OpenRouter, or a hosted
 * provider) when LLM_BASE_URL is set. Otherwise route the model id through the
 * Vercel AI Gateway with AI_GATEWAY_API_KEY.
 */
const baseUrl = process.env.LLM_BASE_URL?.trim();
const apiKey = process.env.LLM_API_KEY?.trim();
const modelId = process.env.LLM_MODEL?.trim() || "openai/gpt-5.4-mini";

const workflow = {
  experimental: {
    workflow: {
      world: "@workflow/world-postgres",
      // Keep completed session transcripts readable. Canonical messages are
      // also stored in PostgreSQL by the channel, but eve still needs its own
      // session history for multi-turn conversations.
      retention: "default" as const,
    },
  },
  build: {
    externalDependencies: ["@workflow/world-postgres"],
  },
};

const directModel = baseUrl
  ? createOpenAICompatible({
      name: "frontdesk",
      baseURL: baseUrl,
      ...(apiKey ? { apiKey } : {}),
      includeUsage: true,
    })
  : null;

const contextWindowTokens = Number(
  process.env.LLM_CONTEXT_WINDOW ?? 128_000,
);

export default defineAgent({
  model: directModel ? directModel(modelId) : modelId,
  // Setting this explicitly keeps `eve build` from needing the AI Gateway
  // model catalog and works for custom OpenAI-compatible endpoints.
  modelContextWindowTokens: contextWindowTokens,
  ...workflow,
});
