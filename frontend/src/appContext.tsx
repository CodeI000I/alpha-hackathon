import { createContext, useContext } from 'react';
import type { Company, Role, User } from './api/types';
export interface WorkspaceContext { user: User; company?: Company; roles: Role[]; activeRole: string; setActiveRole: (role: string) => void; saved: number[]; toggleSaved: (id: number) => void }
export const Workspace = createContext<WorkspaceContext | null>(null);
export function useWorkspace() { const value = useContext(Workspace); if (!value) throw new Error('Workspace is unavailable'); return value; }
