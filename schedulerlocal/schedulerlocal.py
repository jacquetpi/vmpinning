import time
from schedulerlocal.subset.subsetmanager import SubsetManagerPool
from schedulerlocal.apiendpoint.apiendpoint import ApiEndpoint

class SchedulerLocal:
    """
    Main class of the program : watch cpuset usage and VM usage to propose resources
    ...

    Public Methods
    -------
    run()
        Launch scheduler
    """
    def __init__(self, **kwargs):
        req_attributes = ['cpuset', 'memset', 'connector', 'delay']
        for req_attribute in req_attributes:
            if req_attribute not in kwargs: raise ValueError('Missing required argument', req_attributes)
            setattr(self, req_attribute, kwargs[req_attribute])
        
        self.managers_pool = SubsetManagerPool(**kwargs)
        self.api_endpoint = ApiEndpoint(subset_manager_pool=self.managers_pool,
            api_url=kwargs['api_url'], api_port=kwargs['api_port'])
        self.api_endpoint.run()

    def run(self):
        """Run scheduler with specified delay
        ----------
        """
        launch_at = time.time_ns()
        while True:
            time_begin = time.time_ns()

            self.__iteration(time_since_launch=int((time_begin-launch_at)/(10**9)))
            
            time_to_sleep = (self.delay*10**9) - (time.time_ns() - time_begin)
            if time_to_sleep>0: time.sleep(time_to_sleep/10**9)
            else: print('Warning: overlap iteration', -(time_to_sleep/10**9), 's')
        
    def __iteration(self, time_since_launch : int):
        """Execute all actions related to an iteration
        ----------

        """
        self.managers_pool.iterate(timestamp=time_since_launch)

    def __del__(self):
        """Clean endpoint on shutdown
        ----------
        """
        self.api_endpoint.shutdown()