import {
  Calculator,
  Brain,
  BookOpen,
  LineChart,
  Box,
  Code2,
  Compass,
  Briefcase,
} from 'lucide-react';
import type { SkillDomain } from '../types';

export const SKILL_DOMAINS: SkillDomain[] = [
  {
    id: 'numerical_intelligence',
    name: 'Numerical Intelligence',
    category: 'Cognitive',
    description:
      'Quantitative problem solving, numerical sequence recognition, probabilistic estimation, and mathematical reasoning.',
    icon: Calculator,
  },
  {
    id: 'logical_reasoning',
    name: 'Logical Reasoning',
    category: 'Cognitive',
    description:
      'Deductive and inductive logic, syllogistic inference, truth table analysis, and conditional relationship deduction.',
    icon: Brain,
  },
  {
    id: 'verbal_intelligence',
    name: 'Verbal Intelligence',
    category: 'Cognitive',
    description:
      'Lexical precision, contextual comprehension, semantic relationship mapping, and nuanced linguistic analysis.',
    icon: BookOpen,
  },
  {
    id: 'analytical_thinking',
    name: 'Analytical Thinking',
    category: 'Analytical',
    description:
      'Deconstructing complex multifaceted systems, identifying root causes, and formulating structured resolution models.',
    icon: LineChart,
  },
  {
    id: 'spatial_intelligence',
    name: 'Spatial Intelligence',
    category: 'Perceptual',
    description:
      'Mental rotation, visual-spatial transformation, topological reasoning, and 3D geometric structure analysis.',
    icon: Box,
  },
  {
    id: 'programming_logic',
    name: 'Programming Logic',
    category: 'Technical',
    description:
      'Algorithmic execution flow, control state tracing, recursive problem decomposition, and data structure manipulation.',
    icon: Code2,
  },
  {
    id: 'critical_thinking',
    name: 'Critical Thinking',
    category: 'Analytical',
    description:
      'Evaluating argument validity, cognitive bias detection, empirical evidence critique, and logical fallacy analysis.',
    icon: Compass,
  },
  {
    id: 'career_readiness',
    name: 'Career Readiness',
    category: 'Applied',
    description:
      'Technical interview reasoning, practical systems architecture judgment, and professional communication acumen.',
    icon: Briefcase,
  },
];

