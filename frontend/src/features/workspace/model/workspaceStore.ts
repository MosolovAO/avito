import { create } from "zustand"

interface WorkspaceState {
    selectedWorkspaceId: number | null;
    setSelectedWorkspaceId: (workspaceId: number) => void;
    clearSelectedWorkspaceId: () => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  selectedWorkspaceId: null,
  setSelectedWorkspaceId: (workspaceId) => {
    set({ selectedWorkspaceId: workspaceId });
  },
  clearSelectedWorkspaceId: () => {
    set({ selectedWorkspaceId: null });
  },
}));