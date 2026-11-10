import type { LucideIcon } from 'lucide-react';

export type SkillCategory = 'Cognitive' | 'Analytical' | 'Perceptual' | 'Technical' | 'Applied';

export interface SkillDomain {
  id: string;
  name: string;
  category: SkillCategory;
  description: string;
  icon: LucideIcon;
}

export interface UpcomingModule {
  id: string;
  title: string;
  description: string;
  provisionalMilestone: string;
  icon: LucideIcon;
}

