from __future__ import unicode_literals, division, absolute_import

import logging
import re
from jsonschema.compat import str_types
from flexget import plugin
from flexget.event import event
from flexget.entry import Entry

from flexget.config_schema import format_checker

log = logging.getLogger('dynamic_imdb')

JOB_TYPES = ['actor', 'director', 'producer', 'writer', 'self',
             'editor', 'miscellaneous', 'editorial department', 'cinematographer',
             'visual effects', 'thanks', 'music department']

CONTENT_TYPES = ['movie', 'tv series', 'tv mini series', 'video game', 'video movie', 'tv movie', 'episode']

ENTITIES_FORMATS = {
    'Person': r'nm(\d{7})',
    'Company': r'co(\d{7})',
    'Character': r'ch(\d{7})'
}


class DynamicIMDB(object):
    """
    This plugin enables generating entries based on an entity, an entity being a person, character or company.
    It's based on IMDBpy which is required (pip install imdbpy). The basic config required just an IMDB ID of the
    required entity.

    For example:

        smart_imdb: 'http://www.imdb.com/character/ch0001354/?ref_=tt_cl_t1'

    ID format is not important as relevant ID is captured via regex.

    Schema description:
    Other than ID, all other properties are meant to filter the full list that the entity generates.

    id: string that relates to a supported entity type. For example: 'nm0000375'. Required.
    job_types: a string or list with job types from JOB_TYPES. Default is 'actor'.
    content_types: A string or list with content types from CONTENT_TYPES. Default is 'movie'.
    include_genres: A string or list with genres to include when matching a movie. Can also contain match_type,
        which decided on the filter type.
        If match_type is 'any', if ANY of the included genres are listed in the filtered movie, it will pass the filter.
        If match_type is 'all, if ALL of the included genres are listed in the filtered movie, it will pass the filter.
        If match_type is 'exact, if EXACTLY all of the included genres are listed in the filtered movie,
        it will pass the filter. Default match_type is 'any'.
    exclude_genres: Exactly like include_genres but relates to which genres the item should not hold.
    rating: A number between 0 and 10 that will be matched against the rating of the movie. If movie rating is higher
        or equal, it will pass the filter.
    votes: A number that will be matched against the votes of the movie. If movie number of votes is higher
        or equal, it will pass the filter.
    years: A string that determines which years to filter. For example:
        2004: If movie year is 2004, it will pass filter.
        2004-: If movie year is 2004 and higher, it will pass filter.
        -2004: If movie year is before 2004, it will pass filter.
        2000-2004: If movie year is between 2000 and 2004, it will pass filter.
    actor_position: A number great than 0 that specifies the minimum position that an actor must be listed in case in
        order to pass filter. Relevant only when filtering for person and job_types include actor.
    max_entries: The maximum number of entries that can return. This value's purpose is basically flood protection
        against unruly configurations that will return too many results. Default is 200.
    strict_mode: A boolean value that determines what to do in case an item does not have year, rating or votes listed
        and the configuration holds any of those. If set to 'True', it will cause an item that does not hold one of
        these properties to fail the filter. Default is 'False'.

    Advanced config example:
        smart_movie_queue:
            smart_imdb:
              id: 'http://www.imdb.com/company/co0051941/?ref_=fn_al_co_2'
              job_types:
                - actor
                - director
              content_types:
                - tv series
              rating: 5.6
              include_genres:
                genres:
                  - action
                  - comedy
                match_type: any
              exclude_genres: animation
              years: '2005-'
              strict_mode: yes
            accept_all: yes
            movie_queue: add

    """
    job_types = {'type': 'string', 'enum': JOB_TYPES}
    content_types = {'type': 'string', 'enum': CONTENT_TYPES}

    schema = {
        'oneOf': [
            {'type': 'string'},
            {'type': 'object',
             'properties': {
                 'id': {'type': 'string'},
                 'job_types': {
                     'oneOf': [
                         {'type': 'array', 'items': job_types},
                         job_types
                     ]
                 },
                 'content_types': {
                     'oneOf': [
                         {'type': 'array', 'items': content_types},
                         content_types
                     ]
                 },
                 'max_entries': {'type': 'number'}
             },
             'required': ['id'],
             'additionalProperties': False
             }
        ]
    }

    def entity_type_and_object(self, imdb_id):
        """
        Return a tuple of entity type and entity object
        :param imdb_id: string which contains IMDB id
        :return: entity type, entity object (person, company, etc.)
        """
        for imdb_entity_type, imdb_entity_format in ENTITIES_FORMATS.items():
            m = re.search(imdb_entity_format, imdb_id)
            if m:
                if imdb_entity_type == 'Person':
                    log.info('Starting to retrieve items for person: %s' % self.ia.get_person(m.group(1)))
                    return imdb_entity_type, self.ia.get_person(m.group(1))
                elif imdb_entity_type == 'Company':
                    log.info('Starting to retrieve items for company: %s' % self.ia.get_company(m.group(1)))
                    return imdb_entity_type, self.ia.get_company(m.group(1))
                elif imdb_entity_type == 'Character':
                    log.info('Starting to retrieve items for Character: %s' % self.ia.get_character(m.group(1)))
                    return imdb_entity_type, self.ia.get_character(m.group(1))

    def items_by_entity(self, entity_type, entity_object, content_types, job_types):
        """
        Gets entity object and return movie list
        :param entity_type: Person, company, etc.
        :param entity_object: The object itself
        :param content_types: as defined in config
        :param job_types: As defined in config
        :return:
        """
        movies = []

        if entity_type == 'Company':
            return entity_object.get('production companies')

        if entity_type == 'Character':
            return entity_object.get('feature', []) + entity_object.get('tv', []) \
                   + entity_object.get('video-game', []) + entity_object.get('video', [])

        elif entity_type == 'Person':
            if 'actor' in job_types:
                job_types.append('actress')  # Special case: Actress are listed differently than actor
            for job_type in job_types:
                for content_type in content_types:
                    job_and_content = job_type + ' ' + content_type
                    log.debug('Searching for movies that correlates to: ' + job_and_content)
                    movies_by_job_type = entity_object.get(job_and_content, entity_object.get(job_type))
                    if movies_by_job_type:
                        for movie in movies_by_job_type:
                            self.ia.update(movie)
                            if movie not in movies and movie['kind'] in content_types:
                                log.debug('Found item: ' + movie.get('title') + ', adding to unfiltered list')
                                movies.append(movie)
                            else:
                                log.debug('Movie ' + str(movie) + ' already found in list, skipping.')
            return movies

    def prepare_config(self, config):
        """
        Converts config to dict form and sets defaults if needed
        """
        if not isinstance(config, dict):
            config = {'id': config}

        config.setdefault('content_types', [CONTENT_TYPES[0]])
        config.setdefault('job_types', [JOB_TYPES[0]])
        config.setdefault('max_entries', 200)

        if isinstance(config.get('content_types'), str_types):
            log.debug('Converted content type from string to list.')
            config['content_types'] = [config['content_types']]

        if isinstance(config['job_types'], str_types):
            log.debug('Converted job type from string to list.')
            config['job_types'] = [config['job_types']]

        return config

    def on_task_input(self, task, config):
        try:
            from imdb import IMDb
        except Exception:
            log.error('IMDBPY is requires for this plugin. Please install using "pip install imdbpy"')
            return

        self.ia = IMDb()
        entries = []

        config = self.prepare_config(config)

        try:
            entity_type, entity_object = self.entity_type_and_object(config.get('id'))
        except Exception as e:
            log.error('Could not resolve entity via ID. Either error in config or unsupported entity: %s' % e)
            return

        items = self.items_by_entity(entity_type, entity_object,
                                     config.get('content_types'), config.get('job_types'))

        if not items:
            log.error('Could not get IMDB item list, check your configuration.')
            return

        log.info('Retrieved %d items.' % len(items))

        for item in items:
            entry = Entry(title=item['title'],
                          imdb_id='tt' + self.ia.get_imdbID(item),
                          url='')
            if entry.isvalid():
                if entry not in entries:
                    entries.append(entry)
                    if entry and task.options.test:
                        log.info("Test mode. Entry includes:")
                        log.info("    Title: %s" % entry["title"])
                        log.info("    IMDB ID: %s" % entry["imdb_id"])
            else:
                log.error('Invalid entry created? %s' % entry)

        if len(entries) <= config.get('max_entries'):
            return entries
        else:
            log.warning(
                'Number of entries (%s) exceeds maximum allowed value %s. '
                'Edit your filters or raise the maximum value by entering a higher "max_entries"' % (
                    len(entries), config.get('max_entries')))
            return


@event('plugin.register')
def register_plugin():
    plugin.register(DynamicIMDB, 'dynamic_imdb', api_ver=2)
