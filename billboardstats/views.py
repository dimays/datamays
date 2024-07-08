from django.shortcuts import render

# Chart
def chart(request):
    return render(request, 'billboardstats/chart.html')

# Song
def song(request):
    return render(request, 'billboardstats/song.html')

# Artist
def artist(request):
    return render(request, 'billboardstats/artist.html')