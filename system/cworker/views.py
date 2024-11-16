from django.shortcuts import render
# myapp/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import Post
from .forms import PostForm


def notification_page_view(request):
    return render(request, 'notification_page.html')


def home(request):
    posts = Post.objects.all()
    return render(request, 'home.html', {'posts': posts})


def add_post(request):
    if request.method == 'POST':
        form = PostForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = PostForm()
    return render(request, 'add_post.html', {'form': form})


def edit_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if request.method == 'POST':
        form = PostForm(request.POST, instance=post)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = PostForm(instance=post)
    return render(request, 'edit_post.html', {'form': form})


def delete_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if request.method == 'POST':
        post.delete()
        return redirect('home')
    return render(request, 'delete_post.html', {'post': post})


def start_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    post.is_running = True
    post.save()
    return redirect('home')


def stop_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    post.is_running = False
    post.save()
    return redirect('home')
