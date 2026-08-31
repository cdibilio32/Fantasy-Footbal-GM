import { OpenAIProvider } from './openai.js';
import { LLMConfig, LLMMessage } from '../types.js';

const DEEPSEEK_BASE_URL = 'https://api.deepseek.com';

export class DeepSeekProvider extends OpenAIProvider {
  constructor(config: LLMConfig) {
    super({ ...config, base_url: config.base_url || DEEPSEEK_BASE_URL });
  }

  async validateConfig(config: Partial<LLMConfig>): Promise<boolean> {
    try {
      if (!config.api_key) return false;

      const testMessages: LLMMessage[] = [
        { role: 'user', content: 'Reply with the single word OK.' }
      ];
      const response = await this.chat(testMessages, { max_tokens: 20 });
      return response.content.trim().length > 0;
    } catch (error) {
      console.error(`${this.name} config validation failed:`, error);
      return false;
    }
  }

  get name(): string {
    return 'DeepSeek';
  }

  get models(): string[] {
    return [
      'deepseek-v4-flash',
      'deepseek-chat',
      'deepseek-reasoner'
    ];
  }

  getPricing(): { input_cost_per_token: number; output_cost_per_token: number; currency: string } {
    // Pricing per DeepSeek API (USD per million tokens, off-peak rate, converted to per token).
    // DeepSeek bills peak (01:00-04:00 and 06:00-10:00 UTC) vs. off-peak; we use the off-peak
    // rate as the conservative default since automation runs aren't scheduled around it.
    const pricingMap: Record<string, any> = {
      'deepseek-v4-flash': { input: 0.22, output: 0.66 },
      'deepseek-chat': { input: 0.28, output: 0.42 },
      'deepseek-reasoner': { input: 0.28, output: 0.42 }
    };

    const pricing = pricingMap[this.config.model] || pricingMap['deepseek-v4-flash'];

    return {
      input_cost_per_token: pricing.input / 1000000,
      output_cost_per_token: pricing.output / 1000000,
      currency: 'USD'
    };
  }
}
