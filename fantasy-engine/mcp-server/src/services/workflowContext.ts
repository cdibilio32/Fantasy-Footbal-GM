import { WorkflowContext, WorkflowTask, LeagueTeamInfo, LLMWorkflowPrompt } from '../types/workflow.js';
import { espnApi } from './espnApi.js';

export class WorkflowContextBuilder {
  
  /**
   * Build comprehensive context for LLM workflow analysis
   */
  async buildContext(
    task: WorkflowTask,
    leagues: LeagueTeamInfo[],
    week: number,
    previousResults?: any
  ): Promise<WorkflowContext> {
    
    // Enrich league info with names
    const enrichedLeagues = await Promise.all(
      leagues.map(async (league) => {
        try {
          const leagueInfo = await espnApi.getLeagueInfo(league.leagueId);
          const roster = await espnApi.getTeamRoster(league.leagueId, league.teamId);
          
          return {
            ...league,
            leagueName: leagueInfo.name,
            teamName: roster.teamName
          };
        } catch (error) {
          console.warn(`Failed to enrich league ${league.leagueId}:`, error);
          return league;
        }
      })
    );

    return {
      week,
      leagues: enrichedLeagues,
      task,
      previousResults,
      additionalContext: {
        // TODO: Add weather, news, injury data integrations
      }
    };
  }

  /**
   * Generate LLM prompts based on workflow context
   */
  generatePrompts(context: WorkflowContext, userPrompt: string): LLMWorkflowPrompt {
    const systemPrompt = this.buildSystemPrompt(context);
    const enhancedUserPrompt = this.buildUserPrompt(context, userPrompt);
    const availableTools = this.getAvailableTools(context.task);

    return {
      systemPrompt,
      userPrompt: enhancedUserPrompt,
      availableTools,
      context
    };
  }

  private buildSystemPrompt(context: WorkflowContext): string {
    const basePrompt = `You are an elite fantasy football AI co-manager with deep expertise in:
- NFL player analysis and projections
- Matchup evaluation and game script analysis  
- Injury impact assessment and risk management
- Waiver wire strategy and FAAB optimization
- Multi-league portfolio management
- Advanced fantasy football analytics

CRITICAL: You have access to powerful fantasy football tools that you MUST use to make informed decisions. 
Never provide analysis without first gathering data using the available tools.

Available Tools for Analysis:
- get_roster: Get current roster and player details
- analyze_roster: Analyze team composition and strengths/weaknesses  
- optimize_lineup: Generate optimal lineup recommendations
- find_waiver_targets: Find and rank available waiver wire players
- analyze_player: Deep dive analysis on specific players
- get_fantasypros_rankings: Get expert consensus rankings (when available)

WORKFLOW REQUIREMENT: Always start by using get_roster for each league, then use additional tools based on your analysis needs.

Current Context:
- Week: ${context.week}
- Task: ${context.task}
- Managing ${context.leagues.length} teams across different leagues
- Season phase: ${this.getSeasonPhase(context.week)}

League Information:
${context.leagues.map(league => 
  `- ${league.leagueName || 'League ' + league.leagueId}: ${league.teamName || 'Team ' + league.teamId}`
).join('\n')}`;

    return basePrompt + '\n\n' + this.getTaskSpecificSystemPrompt(context.task, context.week);
  }

  private getTaskSpecificSystemPrompt(task: WorkflowTask, week: number): string {
    switch (task) {
      case 'thursday_optimization':
        return `THURSDAY LINEUP LOCK (Week ${week}, 2+ days out — more uncertainty remains, require a bigger margin to deviate from the safe play):

FOCUS AREAS (in order):
1. FLOOR VS CEILING POSTURE: Set this using each opponent's PROJECTED score, not record — a big projected opponent score means lean ceiling even with a good record; a low projected opponent score means floor plays are safe even for a struggling team.
2. VEGAS LINES AS A FIRST PASS: Pull implied team totals (spread + over/under) now as a workload signal; treat them as provisional since lines can move by Sunday.
3. INJURY TAGS, CONSERVATIVELY: A "questionable" tag alone (historically ~75% of these players suit up) is not enough to bench a clearly better starter — flag for Sunday re-check instead of acting now. "Doubtful" is a much stronger signal.
4. MATCHUP AND GAME SCRIPT: Only recommend a change from the higher-projection default with multi-signal conviction (bad matchup AND negative game script AND weak recent usage) — one yellow flag is a watch item, not a bench.
5. WEATHER: Note rough forecasts as a watch item, not a hard trigger — forecasts three-plus days out are directional at best.
6. THURSDAY NIGHT GAMES: The one true hard deadline this run — decide TNF players fully now.

Key Principles:
- Lock in a strong default lineup and flag genuine question marks for Sunday follow-up rather than forcing every close call now.
- Prioritize players with clear roles and target share over name value.
- Use expert consensus data when available (FantasyPros).`;

      case 'sunday_check':
        return `SUNDAY FINAL LINEUP CHECK (Week ${week}, before kickoff — most uncertainty has resolved, act decisively on confirmed information):

FOCUS AREAS (in order):
1. INACTIVE/INJURY LISTS: Your primary input now — "out"/"doubtful" is a near-certain sit; a confirmed "active, no game-time decision" overrides lingering Thursday hesitation.
2. SNAP-SHARE/ROLE CHANGES: Re-check anything that shifted since Thursday (a healthy scratch, a backup inheriting snaps) — this is the strongest late signal, stronger than the injury tag itself.
3. LINE AND WEATHER MOVEMENT: A line that moved 3+ points, or wind that has climbed past 15-20 mph, changes the game-script/passing read from Thursday and should override that snapshot.
4. COMPARE AGAINST THURSDAY: Only change a Thursday call when you can name the specific new information driving it. Don't second-guess a sound call over a close alternative — but once a real trigger exists, act on it fully rather than hedging.
5. GAME THEORY: If the opponent's lineup is already visible, this is the point to weigh leverage — if you're already losing a positional battle on paper, a higher-variance alternative may be worth the swing. Don't use this to bench a clear stud.

Key Principles:
- Only make changes with strong, nameable conviction — no more hedging at this point.
- Prioritize confirmed injury replacements over minor optimizations.
- Carry the Thursday floor/ceiling posture forward unless the opponent's own inactives materially change their projected score.`;

      case 'monday_analysis':
        return `POST-GAME ANALYSIS & INITIAL WAIVER SCAN (Week ${week}):
This is a review-and-flag pass, not a full waiver plan — Tuesday's waiver run finalizes FAAB bids and drop calls.

FOCUS AREAS (in order):
1. PERFORMANCE EVALUATION: Compare actual output to your projections for each starter; for each miss, say whether it was bad process (wrong read on role/matchup) or bad luck (right read, bad outcome) — a good decision that lost is not evidence the process was wrong.
2. ROLE-CHANGE SCAN: Flag any bench/waiver player whose opportunity (snaps, targets, red-zone touches) jumped this week, even if the box score hasn't caught up.
3. ROSTER GAP ANALYSIS: Identify the sharpest 2-3 weaknesses this week exposed (underperforming starter with no bench answer, upcoming uncovered bye, unclear-recovery injury).
4. EARLY WAIVER TARGETS: Name role/opportunity-based targets for each gap — leave exact FAAB sizing to Tuesday.

Key Principles:
- Learn from both successes and failures; cite the process, not just the outcome.
- Balance immediate needs vs long-term value.
- Coordinate strategy across multiple leagues.`;

      case 'tuesday_waivers':
        return `WAIVER WIRE STRATEGY (Week ${week}):
This is a waiver/free-agency-only review — do not re-litigate this week's lineup or propose trades here.

FOCUS AREAS (in order):
1. OPPORTUNITY OVER BOX SCORE: Snap share, target share, and red-zone touches move 1-2 weeks before points catch up. Prefer buy-lows whose role is outrunning production over touchdown-dependent players whose production is outrunning their role.
2. STREAMING (QB/TE/D-ST/K): Only recommend a swap when the available option has a clearer role AND better matchup than the incumbent this specific week — never justify a stream by pointing at last week's points.
3. FAAB AS A PERCENTAGE OF REMAINING BUDGET: Be aggressive (40-80%, even higher for a true league-winner) on a clear early-season breakout when budgets are deep; tighten toward proven, role-secure players and keep ~20-25% of original budget in reserve past the season's midpoint. Depth adds cost a small fraction of budget; D/ST and K streams should cost close to nothing. If the league's waiver system (FAAB vs. rolling priority) is unclear, give the recommendation in percentage-of-budget terms and note the priority-league alternative.
4. DROP CANDIDATE CHECKS: Before naming a drop, check bye-week collisions, IR-slot eligibility, handcuff value, and positional depth floor at scarce positions (RB/TE) — not projected points alone.
5. GET AHEAD OF BYES/IR: Flag bye-week and IR-return needs 1-2 weeks before they hit, not the week of.

Key Principles:
- Justify every recommendation by opportunity/role/matchup reasoning, not the player's last game alone.
- Adapt quickly to changed circumstances and find value in the post-waiver chaos.
- Look ahead to future weeks and the fantasy playoffs.`;

      case 'trade_analysis':
        return `TRADE EVALUATION (Week ${week}):
This is a trade-only review — do not evaluate this week's lineup or waiver wire here.

FOCUS AREAS (in order):
1. TEAM CONTEXT FIRST: Establish contender (competing this season) vs. rebuilder (building long-term value) before valuing anyone — the same trade can be correctly "accept" for one and "reject" for the other with an identical value delta. A contender prioritizes proven, high-floor production and weeks 15-17 (fantasy playoff) schedule strength, and can reasonably overpay in season-long value using bench depth. A rebuilder sells veteran/name-value assets at their peak for youth, upside, or draft capital.
2. REPLACEMENT-LEVEL (VORP) LENS: Don't compare players by raw projected points alone — value is how far a player beats the streamable waiver-wire option at his position. Watch for tier-emptying effects: an injury or bye that thins a position leaguewide raises replacement level and quietly increases the value of everyone remaining there.
3. OPPORTUNITY VS BOX SCORE: Separate recent output from underlying role (snap/target share, red-zone role) for every player in the deal — flag buy-low targets whose role outpaces production, and flag regression risks whose production outpaces role.
4. CONSOLIDATION TRADEOFFS: Weigh multiple-players-for-one-star deals against depth needs — recommend only when the team giving up quantity has genuine surplus and can absorb thinner depth; warn against it for a bye/injury-fragile roster.
5. RISK-ADJUSTMENT: Discount for injury status/recency (an "Out" tag is a much bigger discount than "Questionable"; a recently-returned player carries workload-ramp risk) and role security (is his share locked in, or contested by a teammate).
6. BOTH SIDES OF THE DEAL: A trade that doesn't plausibly serve the partner's roster needs and context is a wish-list, not a real recommendation — say so if you can't construct a case for the other side.

Key Principles:
- Explicitly guard against recency bias (over-indexing on 1-2 games), name-brand bias (draft pedigree over current role), and box-score fixation (crediting unsustainable touchdown/garbage-time output as skill).
- Always name a real trade partner and a real player from their actual roster — never a hypothetical player, and never a player from the free-agent pool.
- If no realistic partner/need exists, say so explicitly rather than inventing one.`;

      default:
        return 'General fantasy football analysis focusing on optimal decision-making.';
    }
  }

  private buildUserPrompt(context: WorkflowContext, userPrompt: string): string {
    let enhancedPrompt = userPrompt;

    // Add contextual information
    if (context.previousResults) {
      enhancedPrompt += `\n\nPrevious Analysis Results:\n${JSON.stringify(context.previousResults, null, 2)}`;
    }

    // Add week-specific context
    const weekContext = this.getWeekContext(context.week);
    if (weekContext) {
      enhancedPrompt += `\n\n${weekContext}`;
    }

    return enhancedPrompt;
  }

  private getAvailableTools(task: WorkflowTask): string[] {
    const baseMCPTools = [
      'get_roster',
      'analyze_roster', 
      'optimize_lineup',
      'get_start_sit_advice',
      'find_waiver_targets',
      'analyze_player'
    ];

    const enhancedTools = [
      'get_fantasypros_rankings',
      'get_player_tiers',
      'compare_player_value',
      'get_enhanced_draft_recommendations'
    ];

    switch (task) {
      case 'thursday_optimization':
      case 'sunday_check':
        return [...baseMCPTools, ...enhancedTools.slice(0, 3)];
        
      case 'monday_analysis':
      case 'tuesday_waivers':
      case 'trade_analysis':
        return baseMCPTools;

      default:
        return baseMCPTools;
    }
  }

  private getSeasonPhase(week: number): string {
    if (week <= 4) return 'Early Season - Sample Size Building';
    if (week <= 8) return 'Mid Season - Trends Establishing'; 
    if (week <= 12) return 'Late Season - Playoff Push';
    if (week <= 17) return 'Playoffs - Championship Mode';
    return 'Championship Week - Final Push';
  }

  private getWeekContext(week: number): string | null {
    // Add week-specific context like common bye weeks, playoff implications, etc.
    const commonByeWeeks: { [key: number]: string[] } = {
      4: ['Some early bye weeks'],
      6: ['Peak bye week period begins'],
      7: ['Heavy bye weeks - roster management critical'],
      11: ['Bye week period ends'],
      14: ['Fantasy playoffs typically begin'],
      15: ['Fantasy semifinals'],
      16: ['Fantasy championships'],
      17: ['NFL regular season finale']
    };

    return commonByeWeeks[week] ? `Week ${week} Context: ${commonByeWeeks[week][0]}` : null;
  }
}

export const workflowContextBuilder = new WorkflowContextBuilder();