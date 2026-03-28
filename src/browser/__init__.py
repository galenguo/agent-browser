# Browser subpackage - import lazily to avoid pulling in patchright/cloakbrowser in API-only containers
from .instance_pool import BrowserInstancePool
