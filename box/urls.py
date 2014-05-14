from __future__ import absolute_import, unicode_literals

from django.conf import settings
from django.conf.urls import url, include, patterns
from django.contrib import admin
from django.views import generic

from elephantblog.feeds import EntryFeed


admin.autodiscover()


urlpatterns = patterns(
    '',
    url(r'^admin/', include(admin.site.urls)),
    url(r'^404/$', generic.TemplateView.as_view(template_name='404.html')),
    url(r'^feeds/news/$', EntryFeed()),
)

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += patterns(
        '',
        url(r'^__debug__/', include(debug_toolbar.urls)),
        url(r'^media/(?P<path>.*)$', 'django.views.static.serve',
            {'document_root': settings.MEDIA_ROOT}),
    )

    from django.contrib.staticfiles.urls import staticfiles_urlpatterns
    urlpatterns += staticfiles_urlpatterns()

urlpatterns += patterns(
    '',
    url(r'', include('feincms.contrib.preview.urls')),
    url(r'', include('feincms.urls')),
)
