// src/features/auth/model/schemas.ts
import { z } from "zod";

export const loginSchema = z.object({
  email: z.string().trim().email("Введите корректный email"),
  password: z.string().min(1, "Введите пароль"),
});

export const registerSchema = z
  .object({
    email: z.string().trim().email("Введите корректный email"),
    password: z.string().min(8, "Минимум 8 символов"),
    confirmPassword: z.string().min(1, "Повторите пароль"),
    first_name: z.string().trim().optional(),
    last_name: z.string().trim().optional(),
    workspace_name: z.string().trim().min(1, "Введите название кабинета"),
  })
  .refine((data) => data.password === data.confirmPassword, {
    path: ["confirmPassword"],
    message: "Пароли не совпадают",
  });

export const registerByInvitationSchema = z
  .object({
    password: z.string().min(8, "Минимум 8 символов"),
    confirmPassword: z.string().min(1, "Повторите пароль"),
    first_name: z.string().trim().optional(),
    last_name: z.string().trim().optional(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    path: ["confirmPassword"],
    message: "Пароли не совпадают",
  });

export type LoginFormValues = z.infer<typeof loginSchema>;
export type RegisterFormValues = z.infer<typeof registerSchema>;
export type RegisterByInvitationFormValues = z.infer<
  typeof registerByInvitationSchema
>;
