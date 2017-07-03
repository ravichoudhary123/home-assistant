"""
Support for Snips on-device ASR and NLU.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/snips/
"""
import asyncio
import copy
import json
import logging
import voluptuous as vol
from homeassistant.helpers import template, script, config_validation as cv
import homeassistant.loader as loader

DOMAIN = 'snips'
DEPENDENCIES = ['mqtt']
CONF_INTENTS = 'intents'
CONF_ACTION = 'action'

INTENT_TOPIC = 'hermes/nlu/intentParsed'

# Response keys
INTENT_KEY = 'intent'
INPUT_KEY = 'input'
INTENT_NAME_KEY = 'intentName'
SLOTS_KEY = 'slots'
SLOT_NAME_KEY = 'slotName'
VALUE_KEY = 'value'
KIND_KEY = 'kind'

LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: {
        CONF_INTENTS: {
            cv.string: {
                vol.Optional(CONF_ACTION): cv.SCRIPT_SCHEMA,
            }
        }
    }
}, extra=vol.ALLOW_EXTRA)

INTENT_SCHEMA = vol.Schema({
    vol.Required(INPUT_KEY): str,
    vol.Required(INTENT_KEY): {
        vol.Required('%s' % INTENT_NAME_KEY): str
    },
    vol.Optional(SLOTS_KEY): [{
        vol.Required(SLOT_NAME_KEY): str,
        vol.Required(VALUE_KEY): {
            vol.Required(KIND_KEY): str,
            vol.Required(VALUE_KEY): cv.match_all
        }
    }]
}, extra=vol.ALLOW_EXTRA)


@asyncio.coroutine
def async_setup(hass, config):
    """Activate Snips component."""
    mqtt = loader.get_component('mqtt')
    intents = config[DOMAIN].get(CONF_INTENTS, dict())
    attached_intents = attach_intents(hass, intents)

    @asyncio.coroutine
    def message_received(topic, payload, qos):
        """Handle new messages on MQTT."""
        LOGGER.debug("New intent: %s", payload)
        yield from handle_intent(payload, attached_intents)

    yield from mqtt.async_subscribe(hass, INTENT_TOPIC, message_received)

    return True


def attach_intents(hass, intents):
    """Attach hass to the intents"""
    attached_intents = copy.deepcopy(intents)
    template.attach(hass, attached_intents)

    for name, intent in attached_intents.items():
        if CONF_ACTION in intent:
            intent[CONF_ACTION] = script.Script(
                hass, intent[CONF_ACTION], "Snips intent {}".format(name))

    return attached_intents


def handle_intent(payload, intents):
    """Handle an intent."""
    try:
        response = json.loads(payload)
    except TypeError:
        LOGGER.error('Received invalid JSON: %s', payload)
        return

    try:
        response = INTENT_SCHEMA(response)
    except vol.Invalid as err:
        LOGGER.error('Intent has invalid schema: %s. %s', err, response)
        return

    intent = response[INTENT_KEY][INTENT_NAME_KEY].split('__')[-1]
    config = intents.get(intent)

    if config is None:
        LOGGER.warning("Received unknown intent %s. %s", intent, response)
        return

    action = config.get(CONF_ACTION)

    if action is not None:
        slots = parse_slots(response)
        yield from action.async_run(slots)


def parse_slots(response):
    """Parse the intent slots."""
    parameters = dict()

    for slot in response.get(SLOTS_KEY, []):
        key = slot[SLOT_NAME_KEY]
        value = slot[VALUE_KEY][VALUE_KEY]
        if value is not None:
            parameters[key] = value

    return parameters
