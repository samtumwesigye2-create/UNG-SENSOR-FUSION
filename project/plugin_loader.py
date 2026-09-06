"""
Plugin Loading
==============
Drop a new Sensor or Actuator subclass into a plugins directory and have
it register itself, instead of hand-editing a registry dict.

Runtime code loading is an attack surface by construction: anyone who can
write a file into the plugins directory can execute arbitrary code in the
fusion process. There is intentionally no network-facing upload endpoint.
Every successfully loaded plugin is logged with a SHA-256 digest.
"""
import hashlib, importlib.util, logging, os, sys
logger=logging.getLogger("sensor_fusion")
SENSOR_REGISTRY={}
ACTUATOR_REGISTRY={}

def register_sensor(name:str):
    def _decorator(cls):
        if name in SENSOR_REGISTRY and SENSOR_REGISTRY[name] is not cls:
            logger.warning("Sensor plugin '%s' is overriding an existing registration",name)
        SENSOR_REGISTRY[name]=cls
        return cls
    return _decorator

def register_actuator(name:str):
    def _decorator(cls):
        if name in ACTUATOR_REGISTRY and ACTUATOR_REGISTRY[name] is not cls:
            logger.warning("Actuator plugin '%s' is overriding an existing registration",name)
        ACTUATOR_REGISTRY[name]=cls
        return cls
    return _decorator

def _sha256_of(path:str)->str:
    h=hashlib.sha256()
    with open(path,"rb") as f: h.update(f.read())
    return h.hexdigest()

class PluginLoader:
    def __init__(self,plugins_dir:str):
        self.plugins_dir=plugins_dir; self.loaded=[]; self.failed=[]
    def discover(self):
        if not os.path.isdir(self.plugins_dir):
            logger.warning("Plugin directory not found: %s - no plugins loaded",self.plugins_dir); return
        candidates=sorted(fname for fname in os.listdir(self.plugins_dir) if fname.endswith(".py") and not fname.startswith("_"))
        if not candidates:
            logger.info("No plugin files found in %s",self.plugins_dir); return
        for fname in candidates: self._load_one(os.path.join(self.plugins_dir,fname))
    def _load_one(self,path:str):
        module_name=f"fusion_plugin_{os.path.splitext(os.path.basename(path))[0]}"
        try: digest=_sha256_of(path)
        except OSError as e:
            logger.error("PLUGIN LOAD FAILED path=%s: %s",path,e); self.failed.append({"path":path,"error":str(e)}); return
        try:
            spec=importlib.util.spec_from_file_location(module_name,path)
            if spec is None or spec.loader is None: raise ImportError(f"could not build an import spec for {path}")
            module=importlib.util.module_from_spec(spec); sys.modules[module_name]=module; spec.loader.exec_module(module)
        except Exception as e:
            logger.error("PLUGIN LOAD FAILED path=%s sha256=%s: %s",path,digest,e); self.failed.append({"path":path,"error":str(e)}); sys.modules.pop(module_name,None); return
        logger.warning("PLUGIN LOADED name=%s path=%s sha256=%s",module_name,path,digest); self.loaded.append({"name":module_name,"path":path,"sha256":digest})
    def status(self)->dict:
        return {"loaded":self.loaded,"failed":self.failed,"sensor_types":sorted(SENSOR_REGISTRY.keys()),"actuator_types":sorted(ACTUATOR_REGISTRY.keys())}
