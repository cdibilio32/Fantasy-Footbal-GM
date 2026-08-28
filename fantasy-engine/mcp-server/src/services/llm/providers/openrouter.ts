import { OpenAIProvider } from './openai.js';
import { LLMConfig, LLMMessage } from '../types.js';

const OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1';

export class OpenRouterProvider extends OpenAIProvider {
  constructor(config: LLMConfig) {
    super({ ...config, base_url: config.base_url || OPENROUTER_BASE_URL });
  }

  async validateConfig(config: Partial<LLMConfig>): Promise<boolean> {
    try {
      if (!config.api_key) return false;

      // Reasoning models (like gpt-oss-20b) spend part of max_tokens on hidden
      // reasoning before the visible answer, so the base class's 10-token probe
      // always comes back empty. Give it enough room to actually respond.
      const testMessages: LLMMessage[] = [
        { role: 'user', content: 'Reply with the single word OK.' }
      ];
      const response = await this.chat(testMessages, { max_tokens: 50 });
      return response.content.trim().length > 0;
    } catch (error) {
      console.error(`${this.name} config validation failed:`, error);
      return false;
    }
  }

  get name(): string {
    return 'OpenRouter';
  }

  get models(): string[] {
    return [
      'openai/gpt-oss-20b',
      'openai/gpt-oss-120b',
      'anthropic/claude-3.5-sonnet',
      'google/gemini-2.0-flash-exp',
      'meta-llama/llama-3.1-70b-instruct'
    ];
  }

  getPricing(): { input_cost_per_token: number; output_cost_per_token: number; currency: string } {
    // Pricing per OpenRouter (USD per million tokens, converted to per token)
    const pricingMap: Record<string, any> = {
      'openai/gpt-oss-20b': { input: 0.05, output: 0.20 },
      'openai/gpt-oss-120b': { input: 0.15, output: 0.60 }
    };

    const pricing = pricingMap[this.config.model] || pricingMap['openai/gpt-oss-20b'];

    return {
      input_cost_per_token: pricing.input / 1000000,
      output_cost_per_token: pricing.output / 1000000,
      currency: 'USD'
    };
  }
}
