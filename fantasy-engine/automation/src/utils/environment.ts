import { espnApi, llmConfig } from '@fantasy-ai/shared';

export async function initializeEnvironment(): Promise<void> {
  // Initialize ESPN API with cookies
  const ESPN_S2 = process.env.ESPN_S2;
  const ESPN_SWID = process.env.ESPN_SWID;
  
  if (!ESPN_S2 || !ESPN_SWID) {
    throw new Error('ESPN_S2 and ESPN_SWID environment variables are required');
  }
  
  espnApi.setCookies({
    espn_s2: ESPN_S2,
    swid: ESPN_SWID
  });
  
  console.log('✅ ESPN cookies configured');
  
  // Initialize LLM configuration
  try {
    const llmInitialized = await llmConfig.initializeLLM();
    if (!llmInitialized) {
      console.warn('⚠️ LLM provider initialization failed - continuing without LLM');
    } else {
      console.log('✅ LLM provider initialized');
    }
  } catch (error: any) {
    console.warn(`⚠️ LLM initialization error: ${error.message}`);
  }
  
  // Test ESPN connection with a simple API call
  try {
    const leagueId = process.env.LEAGUE_1_ID || process.env.LEAGUE_ID_1 || process.env.ESPN_LEAGUE_ID;
    if (leagueId) {
      const leagueInfo = await espnApi.getLeagueInfo(leagueId);
      console.log(`✅ ESPN connection verified - League: ${leagueInfo.name}`);
    } else {
      console.log('⚠️ No league ID provided for connection test');
    }
  } catch (error: any) {
    console.warn(`⚠️ ESPN connection test failed: ${error.message}`);
  }
}

export function validateEnvironment(): {
  valid: boolean;
  missing: string[];
} {
  const required = [
    'ESPN_S2',
    'ESPN_SWID'
  ];
  
  const optional = [
    'LEAGUE_1_ID',
    'LEAGUE_1_TEAM_ID',
    'DEEPSEEK_API_KEY',
    'OPENROUTER_API_KEY',
    'GEMINI_API_KEY',
    'CLAUDE_API_KEY',
    'OPENAI_API_KEY'
  ];

  const missing = required.filter(env => !process.env[env]);
  const hasLLM = optional.slice(2).some(env => process.env[env]); // Check for any LLM key

  if (!hasLLM) {
    missing.push('At least one LLM API key (DEEPSEEK_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY, CLAUDE_API_KEY, or OPENAI_API_KEY)');
  }
  
  return {
    valid: missing.length === 0,
    missing
  };
}

export function getCurrentWeek(): number {
  const now = new Date();
  const seasonStart = getNflWeek1Kickoff(now.getFullYear());
  const daysDiff = Math.floor((now.getTime() - seasonStart.getTime()) / (1000 * 3600 * 24));

  if (daysDiff < 0) return 1;
  return Math.min(Math.floor(daysDiff / 7) + 1, 18);
}

// NFL Week 1 kicks off the Thursday following Labor Day (the first Monday of September).
// A flat "September 1st" assumption drifts by up to a week depending on what weekday
// September 1st falls on, so compute Labor Day first and offset from there.
function getNflWeek1Kickoff(year: number): Date {
  const sept1 = new Date(year, 8, 1);
  const daysUntilMonday = (1 - sept1.getDay() + 7) % 7;
  const laborDay = new Date(year, 8, 1 + daysUntilMonday);
  return new Date(year, 8, laborDay.getDate() + 3);
}