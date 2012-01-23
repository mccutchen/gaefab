from __future__ import with_statement

import base64
import datetime
import logging
import os
import sys

from google.appengine.ext import db
from django.utils import simplejson as json


DATE_FORMAT = '%Y-%m-%d'
DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S'


def json_encoder(obj):
    """Objects are encoded as one-item dictionaries mapping '__TYPENAME__' to
    a serializable representation of the type.
    """

    # Dates and datetimes are encoded in a known format
    if isinstance(obj, datetime.datetime):
        return { '__datetime__': obj.strftime(DATETIME_FORMAT) }
    elif isinstance(obj, datetime.date):
        return { '__date__': obj.strftime(DATE_FORMAT) }

    # Blobs are base64-encoded
    elif isinstance(obj, db.Blob):
        return { '__blob__': base64.b64encode(obj) }

    # Keys are encoded as a 3-element list of [kind, id_or_name, parent]
    # where the parent can be null or another key.
    elif isinstance(obj, db.Key):
        return {
            '__key__': [
                obj.kind(),
                obj.id_or_name(),
                json_encoder(obj.parent())
                ]
            }

    # Models are encoded as just their key
    elif isinstance(obj, db.Model):
        return json_encoder(obj.key())

    # There was no special encoding to be done
    return obj

def json_decoder(dct):
    """Decodes objects encoded as one-item dictionaries. See `json_encoder`.

    NOTE: Models are deserialized as their keys, under the assumption that the
    place(s?) where a model would be serialized (e.g., ReferenceProperty)
    accept either a model or its key as a value.
    """
    if len(dct) == 1:
        type_name, value = dct.items()[0]
        type_name = type_name.strip('_')
        if type_name == 'datetime':
            return datetime.datetime.strptime(value, DATETIME_FORMAT)
        elif type_name == 'date':
            return datetime.datetime.strptime(value, DATE_FORMAT).date()
        elif type_name == 'blob':
            return db.Blob(base64.b64decode(value))
        elif type_name == 'key':
            kind, keydata, parent = value
            return db.Key.from_path(kind, keydata, parent=parent)
    return dct

def load_fixtures(filename):
    """Loads fixtures from the given path into the datastore."""
    logging.info("Loading fixtures from %s..." % os.path.basename(filename))

    with open(filename, 'r') as f:
        json_obj = json.load(f, object_hook=json_decoder)

    # TODO: Batch the creation process for more efficiency?
    for count, data in enumerate(json_obj):
        model = get_model(data['model'])
        create_entity(model, data.get('key'), data['fields'])

    logging.info("Loaded %d fixtures..." % (count + 1))

def get_model(modelspec):
    """Gets the model class specified in the given modelspec, which should be
    in the format `path.to.models.module.ModelName`.
    """
    # Split the modelspec into module path and model name
    module_name, model = modelspec.rsplit('.', 1)
    # Import the module
    __import__(module_name, {}, {})
    # Get a reference to the actual module object
    module = sys.modules[module_name]
    # Return the model class from the module
    return getattr(module, model)

def create_entity(model, key, fields):
    """Creates an entity of the given type in the datastore, based on the
    given fields.
    """

    logging.debug('Creating %s entity with key %r' % (model.kind(), key))

    # The final keyword arguments we'll pass to the entity's constructor
    args = { 'key': key }

    # Gather up the field names and values into the args dict.  The names must
    # be cast to strings to be usable as keyword arguments.
    for field, value in fields.iteritems():
        # Any special casing based on property type should happen here
        args[str(field)] = value

    # Create and store the entity
    return model(**args).put()

def serialize_entities(modelspec):
    """Serializes all of the entities of the kind specified by the given
    modelspec as JSON.
    """
    model = get_model(modelspec)
    fields = model.properties()

    def prep_fields(entity):
        # We have to go head and run the json_encoder over the entity's fields
        # here to properly handle db.Blob properties, which are subclasses of
        # `str` and therefore do not get sent through the json_encoder as you
        # might hope they would be.
        return dict((name, json_encoder(getattr(entity, name)))
                    for name in fields)

    entities = [
        { 'model': modelspec,
          'key': entity.key(),
          'fields': prep_fields(entity) }
        for entity in model.all()]

    return json.dumps(entities, default=json_encoder, indent=4)
