import codecs
import collections
import json
import operator

import redis
from rest_framework import generics
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.response import Response

from ara.api import filters, models, serializers
from ara.server import settings
from ara.ui import forms
from ara.ui.pagination import LimitOffsetPaginationWithLinks


class Index(generics.ListAPIView):
    """
    Returns a list of playbook summaries
    """

    queryset = models.Playbook.objects.all()
    filterset_class = filters.PlaybookFilter
    renderer_classes = [TemplateHTMLRenderer]
    pagination_class = LimitOffsetPaginationWithLinks
    template_name = "index.html"

    def get(self, request, *args, **kwargs):
        query = self.filter_queryset(self.queryset.all().order_by("-id"))
        page = self.paginate_queryset(query)
        if page is not None:
            serializer = serializers.ListPlaybookSerializer(page, many=True)
        else:
            serializer = serializers.ListPlaybookSerializer(query, many=True)
        response = self.get_paginated_response(serializer.data)

        if self.paginator.count > (self.paginator.offset + self.paginator.limit):
            max_current = self.paginator.offset + self.paginator.limit
        else:
            max_current = self.paginator.count
        current_page_results = "%s-%s" % (self.paginator.offset + 1, max_current)

        # We need to expand the search card if there is a search query, not considering pagination args
        search_args = [arg for arg in request.GET.keys() if arg not in ["limit", "offset"]]
        expand_search = True if search_args else False

        search_form = forms.PlaybookSearchForm(request.GET)

        # fmt: off
        return Response(dict(
            current_page_results=current_page_results,
            data=response.data,
            expand_search=expand_search,
            page="index",
            search_form=search_form,
            static_generation=False
        ))
        # fmt: on


class HostIndex(generics.RetrieveAPIView):
    """
    Returns the latest playbook result for each host (or all playbook results for every hosts)
    """

    renderer_classes = [TemplateHTMLRenderer]
    pagination_class = LimitOffsetPaginationWithLinks
    template_name = "host_index.html"

    def get(self, request, *args, **kwargs):
        search_form = forms.HostSearchForm(request.GET)

        # Sort by updated by default so we have the most recently updated at the top
        order = "-updated"
        if "order" in request.GET:
            order = request.GET["order"]

        # Default is LatestHost (by not requiring "?latest=true") but accept false to
        # return all hosts
        if "latest" in request.GET and request.GET["latest"] == "false":
            queryset = models.Host.objects.all()
            serializer_type = "DetailedHostSerializer"
            filter_type = "HostFilter"
            # TODO: Is there a cleaner way ? Doing this logic in the template seemed complicated.
            checkbox_status = "checked"
            api_link_url = "host-list"
        else:
            queryset = models.LatestHost.objects.all()
            serializer_type = "DetailedLatestHostSerializer"
            filter_type = "LatestHostFilter"
            checkbox_status = ""
            api_link_url = "latesthost-list"

            # Ordering on LatestHost should be applied to the nested host object
            if order.startswith("-"):
                order = "-host__%s" % order[1:]
            else:
                order = "host__%s" % order

            if "updated_after" in request.GET:
                # request.GET is immutable by default, copy it to set host__updated_after instead
                request.GET = request.GET.copy()
                request.GET["host__updated_after"] = request.GET["updated_after"]
                del request.GET["updated_after"]

        query = getattr(filters, filter_type)(request.GET, queryset=queryset)
        page = self.paginate_queryset(query.qs.all().order_by(order))
        if page is not None:
            serializer = getattr(serializers, serializer_type)(page, many=True)
        else:
            serializer = getattr(serializers, serializer_type)(query, many=True)
        response = self.get_paginated_response(serializer.data)

        if self.paginator.count > (self.paginator.offset + self.paginator.limit):
            max_current = self.paginator.offset + self.paginator.limit
        else:
            max_current = self.paginator.count
        current_page_results = "%s-%s" % (self.paginator.offset + 1, max_current)

        # We need to expand the search card if there is a search query, not considering pagination args
        search_args = [arg for arg in request.GET.keys() if arg not in ["limit", "offset"]]
        expand_search = True if search_args else False

        # fmt: off
        return Response(dict(
            api_link_url=api_link_url,
            checkbox_status=checkbox_status,
            current_page_results=current_page_results,
            data=response.data,
            expand_search=expand_search,
            page="host_index",
            search_form=search_form,
            static_generation=False,
        ))
        # fmt: on


class Playbook(generics.RetrieveAPIView):
    """
    Returns a page for a detailed view of a playbook
    """

    queryset = models.Playbook.objects.all()
    renderer_classes = [TemplateHTMLRenderer]
    pagination_class = LimitOffsetPaginationWithLinks
    template_name = "playbook.html"

    def get(self, request, *args, **kwargs):
        play_id = request.GET.get('play', None)
        playbook = serializers.DetailedPlaybookSerializer(self.get_object())
        playbook_id = playbook.data['id']
        hosts = serializers.ListHostSerializer(
            models.Host.objects.filter(playbook=playbook_id).order_by("name").all(),
            many=True
        )
        files = serializers.ListFileSerializer(
            models.File.objects.filter(playbook=playbook_id).all(),
            many=True,
        )
        records = serializers.ListRecordSerializer(
            models.Record.objects.filter(playbook=playbook_id).all(),
            many=True,
        )
        plays = serializers.ListPlaySerializer(
            models.Play.objects.filter(playbook=playbook_id).all(),
            many=True,
        )

        play = max(plays.data, key=lambda data: data['id'])
        if play_id is not None:
            play = next(filter(lambda d: d['id'] == int(play_id), plays.data), None)

        order = "-started"
        if "order" in request.GET:
            order = request.GET["order"]

        result_qs = models.Result.objects.filter(playbook=playbook.data["id"]).order_by(order)
        if play is not None:
            result_qs = result_qs.filter(play=play['id'])

        result_filter = filters.ResultFilter(request.GET, queryset=result_qs)

        page = self.paginate_queryset(result_filter.qs)
        if page is not None:
            serializer = serializers.ListResultSerializer(page, many=True)
        else:
            serializer = serializers.ListResultSerializer(result_filter, many=True)

        # TODO: We should have a serializer that takes care of this automatically instead of backfilling "manually"
        for result in serializer.data:
            task = models.Task.objects.get(pk=result["task"])
            result["task"] = serializers.SimpleTaskSerializer(task).data
            host = models.Host.objects.get(pk=result["host"])
            result["host"] = serializers.SimpleHostSerializer(host).data
            if result["delegated_to"]:
                delegated_to = [models.Host.objects.get(pk=delegated) for delegated in
                                result["delegated_to"]]
                result["delegated_to"] = serializers.SimpleHostSerializer(delegated_to,
                                                                          many=True).data
        paginated_results = self.get_paginated_response(serializer.data)

        if self.paginator.count > (self.paginator.offset + self.paginator.limit):
            max_current = self.paginator.offset + self.paginator.limit
        else:
            max_current = self.paginator.count
        current_page_results = "%s-%s" % (self.paginator.offset + 1, max_current)

        # We need to expand the search card if there is a search query, not considering pagination args
        search_args = [arg for arg in request.GET.keys() if arg not in ["limit", "offset"]]
        expand_search = True if search_args else False

        search_form = forms.ResultSearchForm(request.GET)

        return Response(dict(
            current_page_results=current_page_results,
            expand_search=expand_search,
            files=files.data,
            hosts=hosts.data,
            page="playbook",
            playbook=playbook.data,
            plays=plays.data,
            selected_play=play,
            records=records.data,
            results=paginated_results.data,
            search_form=search_form,
            static_generation=False,
        ))


class Host(generics.RetrieveAPIView):
    """
    Returns a page for a detailed view of a host
    """

    queryset = models.Host.objects.all()
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "host.html"

    def get(self, request, *args, **kwargs):
        host = self.get_object()
        host_serializer = serializers.DetailedHostSerializer(host)

        order = "-started"
        if "order" in request.GET:
            order = request.GET["order"]
        result_queryset = (
            models.Result.objects
                .filter(host=host_serializer.data["id"])
                .order_by(order)
                .all()
        )
        result_filter = filters.ResultFilter(request.GET, queryset=result_queryset)

        page = self.paginate_queryset(result_filter.qs)
        if page is not None:
            result_serializer = serializers.ListResultSerializer(page, many=True)
        else:
            result_serializer = serializers.ListResultSerializer(result_filter, many=True)

        # TODO: We should have a serializer that takes care of this automatically instead of backfilling "manually"
        for result in result_serializer.data:
            task = models.Task.objects.get(pk=result["task"])
            result["task"] = serializers.SimpleTaskSerializer(task).data
            if result["delegated_to"]:
                delegated_to = [models.Host.objects.get(pk=delegated) for delegated in
                                result["delegated_to"]]
                result["delegated_to"] = serializers.SimpleHostSerializer(delegated_to,
                                                                          many=True).data
        paginated_results = self.get_paginated_response(result_serializer.data)

        if self.paginator.count > (self.paginator.offset + self.paginator.limit):
            max_current = self.paginator.offset + self.paginator.limit
        else:
            max_current = self.paginator.count
        current_page_results = "%s-%s" % (self.paginator.offset + 1, max_current)

        # We need to expand the search card if there is a search query, not considering pagination args
        search_args = [arg for arg in request.GET.keys() if arg not in ["limit", "offset"]]
        expand_search = True if search_args else False

        search_form = forms.ResultSearchForm(request.GET)

        # fmt: off
        return Response(dict(
            current_page_results=current_page_results,
            expand_search=expand_search,
            host=host_serializer.data,
            page="host",
            results=paginated_results.data,
            search_form=search_form,
            static_generation=False,
        ))
        # fmt: on


class File(generics.RetrieveAPIView):
    """
    Returns a page for a detailed view of a file
    """

    queryset = models.File.objects.all()
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "file.html"

    def get(self, request, *args, **kwargs):
        file = self.get_object()
        serializer = serializers.DetailedFileSerializer(file)
        return Response({"file": serializer.data, "static_generation": False, "page": "file"})


class Result(generics.RetrieveAPIView):
    """
    Returns a page for a detailed view of a result
    """

    queryset = models.Result.objects.all()
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "result.html"

    def get(self, request, *args, **kwargs):
        # Results can contain a wide array of non-ascii or binary characters, escape them
        codecs.register_error("strict", codecs.lookup_error("surrogateescape"))
        result = self.get_object()
        serializer = serializers.DetailedResultSerializer(result)
        return Response({"result": serializer.data, "static_generation": False, "page": "result"})


class Record(generics.RetrieveAPIView):
    """
    Returns a page for a detailed view of a record
    """

    queryset = models.Record.objects.all()
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "record.html"

    def get(self, request, *args, **kwargs):
        record = self.get_object()
        serializer = serializers.DetailedRecordSerializer(record)
        return Response({"record": serializer.data, "static_generation": False, "page": "result"})


class Dashboard(generics.ListAPIView):
    queryset = models.Host.objects.all()
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "dashboard.html"

    @staticmethod
    def create_cache_key(host: models.Host, play: models.Play):
        return f'dashboard:{host.id}:{play.id}'

    def serialize(self, data):
        cli = None
        pipe = None
        caches = {}
        cache_keys = []
        if settings.USE_REDIS:
            cli = redis.Redis(settings.REDIS_HOST)
            for res in data.values():
                cache_keys.append(self.create_cache_key(res['host'], res['play']))
            for i, res in enumerate(cli.mget(cache_keys)):
                if res is None:
                    caches[cache_keys[i]] = None
                else:
                    caches[cache_keys[i]] = json.loads(res)
            pipe = cli.pipeline()

        states = collections.defaultdict(list)
        for i, key in enumerate(data):
            hostname, playbook_id = key
            if settings.USE_REDIS:
                if (res := caches[cache_keys[i]]) is not None:
                    states[hostname].append(res)
                    continue

            res = data[key]
            state = dict(
                host=serializers.SimpleHostSerializer(res['host']).data,
                play=serializers.PlaySerializer(res['play']).data,
                playbook=serializers.SimplePlaybookSerializer(res['playbook']).data,
                status=res['status'],
            )
            if settings.USE_REDIS:
                pipe.set(cache_keys[i], json.dumps(state))

            states[hostname].append(state)

        if settings.USE_REDIS:
            pipe.execute()
            pipe.close()
            cli.close()

        return collections.OrderedDict(sorted(states.items(), key=operator.itemgetter(0)))

    def get(self, request, *args, **kwargs):
        q = request.GET.get('q', None)
        status = request.GET.get('status', None)
        data = collections.OrderedDict()
        result_qs = (
            models.Result.objects
                .prefetch_related('host', 'play', 'play__playbook')
                .order_by('host__id', 'playbook__id', '-play__id')
        )
        if q is not None:
            result_qs = filters.DashboardFilter(request.GET, result_qs).qs
        results = result_qs.all()

        for r in results:
            key = (r.host.name, r.playbook.id)
            if key not in data:
                data[key] = dict(host=r.host, play=None, playbook=None, status=None)

            if (play := data[key]['play']) is None or r.play.id > play.id:
                data[key]['play'] = r.play
                data[key].update(
                    host=r.host,
                    play=r.play,
                    playbook=r.playbook,
                    status='fail' if r.host.failed + r.host.unreachable > 0 else 'success',
                )
        states = self.serialize(data)

        return Response(dict(
            page='dashboard',
            states=states,
            status=status,
            static_generation=False,
        ))
