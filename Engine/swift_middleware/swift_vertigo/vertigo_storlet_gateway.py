'''===========================================================================
16-Oct-2015    josep.sampe    Initial implementation.
05-Feb-2016    josep.sampe    Added Proxy execution.
01-Mar-2016    josep.sampe    Addded pipeline (multi-node)
==========================================================================='''
from swift.common.swob import Request
from swift.common.swob import HTTPUnauthorized
from storlet_gateway.storlet_docker_gateway import StorletGatewayDocker
import vertigo_common as cc
import json

class VertigoGatewayStorlet():

    def __init__(self, conf, logger, app, v, account, container, obj, method):
        self.conf = conf
        self.logger = logger
        self.app = app
        self.version = v   
        self.account = account
        self.container = container
        self.obj = obj
        self.gateway = None
        self.storlet_metadata = None
        self.storlet_name = None
        self.method = method
        self.server = self.conf['execution_server']
        self.gateway_method = None
          
    def get_storlet_data(self, storlet_data):
        storlet, parameters = storlet_data["storlet"].items()[0]                        
        node = storlet_data["node"]
         
        return storlet, parameters, node
    
    def authorize_storlet_execution(self,storlet):
        resp = cc.make_swift_request("HEAD",self.account,
                                    self.conf["storlet_container"], 
                                    storlet)
        if resp.status_int < 300 and resp.status_int >= 200:
            self.storlet_metadata = resp.headers
            self.storlet_name = storlet
            return True
        return False
           
    def set_storlet_request(self,orig_resp,params): 
               
        self.gateway = StorletGatewayDocker(self.conf, self.logger, self.app, 
                                            self.version, self.account, 
                                            self.container, self.obj)
        
        self.gateway_method = getattr(self.gateway, "gateway" + \
                                      self.server.title() + \
                                      self.method.title() + "Flow")
        
        # Set Storlet Metadata to storletgateway
        self.gateway.storlet_metadata = self.storlet_metadata
  
        # Simulate Storlet request
        new_env = dict(orig_resp.environ)     
        req = Request.blank(new_env['PATH_INFO'], new_env)
        req.headers['X-Run-Storlet'] = self.storlet_name
        self.gateway.augmentStorletRequest(req)
        req.environ['QUERY_STRING'] = params         
        
        return req
    
    def launch_storlet(self, orig_resp, params, input_pipe=None):
        req = self.set_storlet_request(orig_resp, params)      

        (_, app_iter) = self.gateway_method(req, self.container, 
                                            self.obj, orig_resp, 
                                            input_pipe)        
        return app_iter.obj_data, app_iter

    def execute_storlet(self, original_resp, storlet_list):
        storlet_list = json.loads(storlet_list)           
        out_fd = None
        on_proxy = {}    
                         
        # Execute multiple Storlets, PIPELINE, if any.
        for key in sorted(storlet_list):
            # Get Storlet and parameters                 
            storlet, params, node = self.get_storlet_data(storlet_list[key])
                                              
            if node == self.server:
                self.logger.info('Vertigo - Go to execute '+storlet + \
                                 ' storlet with parameters "' +params+'"')
                if not self.authorize_storlet_execution(storlet):
                    return HTTPUnauthorized('Vertigo - Storlet: No permission')

                out_fd, app_iter = self.launch_storlet(original_resp, 
                                                       params, out_fd)     
                # Notify to the Proxy that Storlet was executed in the 
                # object-server
                original_resp.headers["Storlet-Executed"] = True
            
            else:
                storlet_execution = {}
                storlet_execution['storlet'] = {storlet:params}
                storlet_execution['node'] = 'proxy'
                on_proxy[key] = storlet_execution

        original_resp.headers['Vertigo'] = json.dumps(on_proxy)
        original_resp.app_iter = app_iter
        return original_resp         
        
        