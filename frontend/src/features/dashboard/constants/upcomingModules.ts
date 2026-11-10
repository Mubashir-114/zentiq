import { Swords, Zap, Cpu, Trophy, GraduationCap } from 'lucide-react';
import type { UpcomingModule } from '../types';

export interface ArchitectureModule {
  name: string;
  desc: string;
  status: string;
}

/**
 * Centralized platform roadmap definitions.
 * All future milestone designations represent provisional planning targets
 * rather than fixed or guaranteed release commitments.
 */
export const UPCOMING_MODULES: UpcomingModule[] = [
  {
    id: 'skill_arena',
    title: 'Skill Arena',
    description:
      'Timed cognitive challenges, competitive evaluations, and verified domain benchmark scoring.',
    provisionalMilestone: 'Provisional (Milestone 4)',
    icon: Swords,
  },
  {
    id: 'daily_missions',
    title: 'Daily Missions',
    description:
      'Curated daily problem-solving objectives and targeted drills designed for cognitive conditioning.',
    provisionalMilestone: 'Provisional (Planned)',
    icon: Zap,
  },
  {
    id: 'ai_tutor',
    title: 'AI Sentinel Tutor',
    description:
      'Contextual diagnostic explanations, neural hint generation, and personalized cognitive coaching.',
    provisionalMilestone: 'Provisional (Milestone 5)',
    icon: Cpu,
  },
  {
    id: 'duels',
    title: '1v1 Skill Duels',
    description:
      'Synchronous and asynchronous real-time cognitive duels against fellow platform pilots.',
    provisionalMilestone: 'Provisional (Milestone 7)',
    icon: Trophy,
  },
  {
    id: 'career_pathways',
    title: 'Career Pathways',
    description:
      'Industry role benchmarking, technical proficiency mapping, and skill gap calibration.',
    provisionalMilestone: 'Provisional (Milestone 8)',
    icon: GraduationCap,
  },
];

/**
 * Centralized modular architecture lifecycle breakdown.
 * Reflects implemented foundations (M1-M3B) and provisional roadmap targets.
 */
export const ARCHITECTURE_MODULES: ArchitectureModule[] = [
  {
    name: 'ZENTIQ CORE',
    desc: 'Platform foundation, shared state, system telemetry, error handling',
    status: 'Implemented (M1-M3B)',
  },
  {
    name: 'ZENTIQ ACCOUNTS',
    desc: 'Custom user model, session authentication, profile management, dashboard',
    status: 'Implemented (M1-M3B)',
  },
  {
    name: 'ZENTIQ GAMIFICATION',
    desc: 'Immutable XP transaction ledger, streak calculators, badge definitions',
    status: 'Provisional (Planned)',
  },
  {
    name: 'ZENTIQ QUEST',
    desc: 'Daily missions, problem drills, learning progression tracks',
    status: 'Provisional (Planned)',
  },
  {
    name: 'ZENTIQ ARENA',
    desc: 'Timed assessments and competitive skill benchmarks',
    status: 'Provisional (Milestone 4)',
  },
  {
    name: 'ZENTIQ AI',
    desc: 'AI-assisted learning tutor and personalized adaptive feedback',
    status: 'Provisional (Milestone 5)',
  },
  {
    name: 'ZENTIQ INSIGHTS',
    desc: 'Performance analytics, skill radar, historical progress tracking',
    status: 'Provisional (Milestone 6)',
  },
  {
    name: 'ZENTIQ DUEL',
    desc: 'Real-time and turn-based 1v1 user knowledge duels',
    status: 'Provisional (Milestone 7)',
  },
  {
    name: 'ZENTIQ CAREER',
    desc: 'Career-readiness scoring, resume mapping, role alignments',
    status: 'Provisional (Milestone 8)',
  },
];
