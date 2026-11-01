# Models and providers

tuvl calls language models and embedding models through its own HTTP client (`tuvl.llm`). A model is
named `provider/model`; a bare id (`gpt-4o`) is an OpenAI model.

```yaml
kind: AgentModel
metadata: { name: default }
spec:
  model: anthropic/claude-sonnet-4-5
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.2
  max_tokens: 1024
  timeout: 60
```

## Built-in providers

| Provider | Id prefix | Key variable | Endpoint |
|---|---|---|---|
| OpenAI | `openai/` | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| Anthropic | `anthropic/` | `ANTHROPIC_API_KEY` | `https://api.anthropic.com` (Messages API) |
| Google Gemini | `gemini/` | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| Azure OpenAI | `azure/<deployment>` | `AZURE_OPENAI_API_KEY` | `$AZURE_OPENAI_ENDPOINT/openai/v1` |
| Amazon Bedrock | `bedrock/<model id>` | `AWS_BEARER_TOKEN_BEDROCK` | `https://bedrock-runtime.$AWS_REGION.amazonaws.com/openai/v1` |
| Google Vertex AI | `vertex_ai/google/<model>` | `VERTEX_ACCESS_TOKEN` | `https://<location>-aiplatform.googleapis.com/v1beta1/projects/$GOOGLE_CLOUD_PROJECT/locations/<location>/endpoints/openapi` |
| Cohere | `cohere/` | `COHERE_API_KEY` | `https://api.cohere.ai/compatibility/v1` |
| Voyage AI (embeddings only) | `voyage/` | `VOYAGE_API_KEY` | `https://api.voyageai.com/v1` |
| Ollama | `ollama/`, `ollama_chat/` | none | `OLLAMA_BASE_URL` (`http://localhost:11434`) |
| Groq, Mistral, DeepSeek, xAI | `groq/`, `mistral/`, `deepseek/`, `xai/` | `<NAME>_API_KEY` | provider default |
| OpenRouter, Together, Fireworks, Perplexity | `openrouter/`, `together_ai/`, `fireworks_ai/`, `perplexity/` | `OPENROUTER_API_KEY`, `TOGETHERAI_API_KEY`, `FIREWORKS_AI_API_KEY`, `PERPLEXITYAI_API_KEY` | provider default |
| LiteLLM proxy / any gateway | `litellm_proxy/<alias>` | `LITELLM_API_KEY` | your `api_base` (required) |
| LM Studio, vLLM | `lm_studio/`, `vllm/`, `hosted_vllm/` | none | `http://localhost:1234/v1`, `http://localhost:8000/v1` |

`api_key` on the AgentModel wins over the variable; it must be an `${ENV_VAR}` reference.
`api_base` overrides the endpoint. `tuvl check system` lists the variables each model needs.

### Cloud providers

These use each vendor's OpenAI-compatible endpoint, so no cloud SDK is installed.

- **Azure OpenAI** uses the v1 API (`/openai/v1`, no `api-version`). The model is your *deployment
  name*: `azure/my-gpt4o`. Authenticate with the resource's API key; Microsoft Entra tokens are not
  fetched for you.
- **Amazon Bedrock** uses the `bedrock-runtime` OpenAI endpoint with a Bedrock API key
  (`AWS_BEARER_TOKEN_BEDROCK`) and a region (`AWS_REGION`). Only models whose Bedrock model card lists
  the Chat Completions API work; SigV4 / IAM-role credentials are not supported.
- **Vertex AI** uses the OpenAI endpoint of your project (`GOOGLE_CLOUD_PROJECT`, location from
  `GOOGLE_CLOUD_LOCATION`, default `us-central1`; `global` selects the global host). The key is a Google
  access token such as `gcloud auth print-access-token`, which expires after about an hour — for a
  long-running service refresh it into `VERTEX_ACCESS_TOKEN` or put a gateway in front.
- **Cohere** uses its compatibility API. Structured output is sent as Cohere's
  `{"type": "json_object", "schema": …}`; embeddings take no `dimensions` field.
- **Voyage AI** serves embeddings only (the output size is sent as `output_dimension`).

Endpoints and request shapes follow the vendors' documentation (checked 2026-10-17). Ollama is the only
provider exercised against a live service in tuvl's own tests; run `tuvl check system --live` against yours
before relying on one.

## Any other endpoint

Anything that speaks the OpenAI chat-completions API works with `api_base`:

```yaml
spec:
  model: acme/my-model            # any prefix; the part after "/" is sent as the model
  api_base: https://llm.example.com/v1
  api_key: ${ACME_API_KEY}
```

A provider with its own wire format and no OpenAI-compatible endpoint (SageMaker, watsonx, Hugging Face,
Replicate) needs a gateway in front.

## Through a LiteLLM proxy or other gateway

A LiteLLM proxy serves the OpenAI API, so tuvl reaches everything litellm supports through it, with the
provider keys and routing kept on the proxy. The model is the alias from the proxy's `model_list`:

```yaml
kind: AgentModel
metadata: { name: gateway }
spec:
  model: litellm_proxy/my-claude        # or openai/my-claude
  api_base: ${LITELLM_PROXY_URL}        # e.g. http://litellm.internal:4000/v1
  api_key: ${LITELLM_API_KEY}
```

Embeddings take the same two fields:

```yaml
kind: EmbeddingRegistry
spec:
  embeddings:
    - name: gateway-embed
      model: litellm_proxy/embed-alias
      dimensions: 1024
      api_base: ${LITELLM_PROXY_URL}
      api_key: ${LITELLM_API_KEY}
```

Structured output, tool calls and logprobs behave as the model behind the proxy does. Each call is one
extra network hop to a service you run.

## What the client does

- Chat completions with structured output (`json_schema`), tool calls and token logprobs (where the
  provider offers them). Anthropic structured output is a forced tool call; Anthropic has no logprobs,
  so decision confidence comes from the model's reported value.
- Embeddings on any OpenAI-compatible endpoint (`openai/text-embedding-3-small`,
  `gemini/gemini-embedding-001`, `ollama/nomic-embed-text`, `cohere/embed-v4.0`, `voyage/voyage-3`).
- Failures are classified as `timeout`, `rate_limit` (HTTP 429), `transient` (connection errors, 5xx) or
  `llm_error`, which is what a step's `retry.errors` matches. The client does not retry by itself.
- Streaming: `tuvl.llm.astream(...)` takes the arguments of `acompletion` and yields `TextDelta` events while the model writes, then one
  `StreamEnd` carrying the same `Completion` a plain call returns (so token counts and finish reason match). A structured response streams
  as pieces of the JSON text. `timeout` is the longest silence between chunks, not the whole call. A model that "thinks" before it answers
  streams nothing until its answer starts.
- One OpenTelemetry span per call; see [observability](observability.md#5-model-call-spans).

`tuvl check system` lists the variables each model needs; `tuvl check system --live` makes one minimal call per model.
