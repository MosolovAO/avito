import { z } from "zod";

export const createWorkspaceInvitationSchema = z.object({
  email: z.string().trim().email("Введите корректный email"),
  role: z.enum(["admin", "manager", "analyst", "viewer"], {
    message: "Выберите роль",
  }),
});

export type CreateWorkspaceInvitationFormValues = z.infer<
  typeof createWorkspaceInvitationSchema
>;
