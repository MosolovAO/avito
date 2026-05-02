from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User, Workspace, WorkspaceInvitation, WorkspaceMembership
from django.contrib import admin


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
    ordering = ('email',)
    list_display = ('email', 'first_name', 'last_name', 'is_active', 'is_staff')
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ('email', 'first_name', 'last_name')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', "groups", "user_permissions")}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ("email", "password1", "password2", "is_staff", "is_superuser", "is_active")
        }),
    )


class WorkspaceMembershipInline(admin.TabularInline):
    model = WorkspaceMembership
    extra = 0
    autocomplete_fields = ('user', 'invited_by')


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ('name', "slug", "owner", "created_at")
    search_fields = ('name', 'slug', 'owner__email')
    autocomplete_fields = ("owner",)
    inlines = [WorkspaceMembershipInline]


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ("workspace", "user", "role", "status", "joined_at")
    list_filter = ("role", "status")
    search_fields = ("workspace__name", "user__email")
    autocomplete_fields = ("workspace", "user", "invited_by")


@admin.register(WorkspaceInvitation)
class WorkspaceInvitationAdmin(admin.ModelAdmin):
    list_display = ("workspace", "email", "role", "status", "expires_at", "created_at")
    list_filter = ("role", "status")
    search_fields = ("workspace__name", "email")
    autocomplete_fields = ("workspace", "invited_by")
    readonly_fields = ("token", "accepted_at", "created_at", "updated_at")
