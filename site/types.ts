/**
 * TypeScript definitions and utility functions for the CS2 All-Time Continuous MMR System.
 */

export interface MMRHistoryEntry {
    match_id: string;
    date: string;
    map: string;
    team_result: 'win' | 'loss' | 'tie';
    delta: number;
    base_delta: number;
    modifier: number;
    mmr_before: number;
    mmr_after: number;
    hltv: number;
    score_10: number;
    is_calibrating: boolean;
    breakdown: string;
}

export interface PlayerMMR {
    current_mmr: number;
    peak_mmr: number;
    last_delta: number;
    wins: number;
    losses: number;
    ties: number;
    win_rate: number;
    avg_hltv: number;
    is_calibrating: boolean;
    is_inactive: boolean;
    form_dots: Array<'win_high' | 'win_low' | 'tie' | 'loss'>;
    sparkline: number[];
    history: MMRHistoryEntry[];
}

export interface LeaderboardRow {
    rank: number;
    steam_id: string;
    name: string;
    avatar_initials: string;
    mmr: number;
    peak_mmr: number;
    last_delta: number;
    last_delta_text: string;
    hltv_rating: number;
    rating: number; // 1.0 - 10.0 scale
    wins: number;
    losses: number;
    win_rate: number;
    total_matches: number;
    form_dots: Array<'win_high' | 'win_low' | 'tie' | 'loss'>;
    is_calibrating: boolean;
    is_inactive: boolean;
    kd_ratio: number;
    adr: number;
    kast: number;
    hs: number;
    roles: string[];
}

export interface PlayerProfile {
    steam_id: string;
    name: string;
    ratings: number[];
    ratings_dict: Record<string, number>;
    roles: string[];
    total_matches: number;
    mmr: PlayerMMR;
    stats: {
        kd: number;
        adr: number;
        kast: number;
        hs: number;
        win_rate: number;
        fk_rate: number;
        clutch_rate: number;
        util_dmg: number;
    };
    strengths: string[];
    weaknesses: string[];
    recommendations: {
        training: string[];
        habits_to_remove: string[];
        exercises: string[];
        best_role: string;
    };
}

/**
 * Format an MMR delta value with plus/minus sign and CSS badge class.
 */
export function formatMMRDelta(delta: number): { text: string; cssClass: string } {
    if (delta > 0) {
        return {
            text: `+${delta}`,
            cssClass: 'bg-emerald-950 text-emerald-300 border border-emerald-500/50'
        };
    } else if (delta < 0) {
        return {
            text: `${delta}`,
            cssClass: 'bg-rose-950 text-rose-300 border border-rose-500/50'
        };
    }
    return {
        text: '0',
        cssClass: 'bg-slate-800 text-slate-400 border border-slate-700'
    };
}

/**
 * Format a form dot into CSS color and tooltip description.
 */
export function getFormDotConfig(type: 'win_high' | 'win_low' | 'tie' | 'loss'): { bg: string; title: string } {
    switch (type) {
        case 'win_high':
            return { bg: 'bg-emerald-400 shadow-emerald-400/50', title: 'Победа (Высокий импакт)' };
        case 'win_low':
            return { bg: 'bg-amber-400 shadow-amber-400/50', title: 'Победа (Средний импакт / Сейв)' };
        case 'tie':
            return { bg: 'bg-blue-400 shadow-blue-400/50', title: 'Ничья' };
        case 'loss':
        default:
            return { bg: 'bg-rose-500 shadow-rose-500/50', title: 'Поражение' };
    }
}
