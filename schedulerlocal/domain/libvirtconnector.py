import libvirt, time
from schedulerlocal.domain.libvirtxmlmodifier import xmlDomainNuma, xmlDomainMetaData
from schedulerlocal.domain.domainentity import DomainEntity

class LibvirtConnector(object):
    """
    A class used as an interface with libvirt API
    ...

    Attributes
    ----------
    url : str
        hypervisor url

    """
    def __init__(self, **kwargs):
        req_attributes = ['url']
        for req_attribute in req_attributes:
            if req_attribute not in kwargs: raise ValueError('Missing required argument', req_attributes)
            setattr(self, req_attribute, kwargs[req_attribute])
        # Connect to libvirt url    
        self.conn = libvirt.open(self.url)
        if not self.conn:
            raise SystemExit('Failed to open connection to ' + self.url)
        self.cache_entity = dict()
        
    def get_vm_alive(self):
        """Retrieve list of VM being running currently as libvirt object
        ----------

        Returns
        -------
        vm_alive : list
            list of virDomain
        """
        return [self.conn.lookupByID( vmid ) for vmid in self.conn.listDomainsID()]

    def get_vm_alive_as_entity(self):
        """Retrieve list of VM being running currently as DomainEntity object
        ----------

        Returns
        -------
        vm_alive : list
            list of DomainEntity
        """ 
        return [self.convert_to_entitydomain(virDomain=vm_virDomain) for vm_virDomain in self.get_vm_alive()]

    def get_vm_shutdown(self):
        """Retrieve list of VM being shutdown currently as libvirt object
        ----------

        Returns
        -------
        vm_shutdown : list
            list of virDomain
        """
        return [self.conn.lookupByName(name) for name in self.conn.listDefinedDomains()]

    def get_all_vm(self):
        """Retrieve list of all VM
        ----------

        Returns
        -------
        vm_list : list
            list of virDomain
        """
        vm_list = self.get_vm_alive()
        vm_list.extend(self.get_vm_shutdown())
        return vm_list

    def print_vm_topology(self):
        """Print all VM topology
        ----------

        """
        for domain in self.get_vm_alive():
            domain_xml = xmlDomainNuma(xml_as_str=domain.XMLDesc())
            print(domain_xml.convert_to_str_xml())
            #self.conn.defineXML(domain_xml.convert_to_str_xml())

    def convert_to_entitydomain(self, virDomain : libvirt.virDomain, force_update = False):
        """Convert the libvirt virDomain object to the domainEntity domain
        ----------

        Parameters
        ----------
        virDomain : libvirt.virDomain
            domain to be converted
        force_update : bool
            Force update of cache

        Returns
        -------
        domain : DomainEntity
            domain as DomainEntity object
        """
        # Cache management
        uuid = virDomain.UUIDString()
        if (not force_update) and uuid in self.cache_entity: return self.cache_entity[uuid]
        # General info
        name = virDomain.name()
        mem = virDomain.maxMemory()
        cpu = virDomain.maxVcpus()
        cpu_pin = virDomain.vcpuPinInfo()
        # Custom metadata
        xml_manager = xmlDomainMetaData(xml_as_str=virDomain.XMLDesc())
        xml_manager.convert_to_object()
        if xml_manager.updated() : 
            self.conn.defineXML(xml_manager.convert_to_str_xml()) # Will only be applied after a restart
            print('Warning, no oversubscription found on domain', name, ': defaults were generated')
        cpu_ratio = xml_manager.get_oversub_ratios()['cpu']
        # Build entity
        self.cache_entity[uuid] = DomainEntity(uuid=uuid, name=name, mem=mem, cpu=cpu, cpu_pin=cpu_pin, cpu_ratio=cpu_ratio)
        return self.cache_entity[uuid]

    def update_cpu_pinning(self, vm : DomainEntity, template_pin : tuple):
        """Update the pinning of a VM to the list of cpuid if required
        ----------

        Parameters
        ----------
        vm_uuid : str
            VM identifier
        template_pin : tuple
            libvirt pinning template
        """
        # Retrieve VM
        virDomain = self.conn.lookupByUUIDString(vm.get_uuid())
        vm_pin       = virDomain.vcpuPinInfo()
    
        # Test if update is needed
        update_needed = False
        for vcpu_pin in vm_pin:
            if vcpu_pin != template_pin: 
                update_needed = True
                break

        # Update
        if update_needed: 
            for vcpu in range(len(vm_pin)): virDomain.pinVcpu(vcpu, template_pin)

    def build_cpu_pinning(self, cpu_list : list, host_config : int):
        """Return Libvirt template of cpu pinning based on authorised list of cpu
        ----------

        Parameters
        ----------
        cpu_list : list
            List of ServerCPU 
        host_config : int
           Number of core on host
        Returns
        -------

        template : Tuple
            Pinning template
        """
        template_pin = [False for is_cpu_pinned in range(host_config)]
        for cpu in cpu_list: template_pin[cpu.get_cpu_id()] = True
        return tuple(template_pin)

    def cache_purge(self):
        """Purge cache associating VM uuid to their domainentity representation
        ----------
        """
        del self.cache_entity
        self.cache_entity = dict()

    def get_usage_cpu(self, vm : DomainEntity):
        """Return the latest CPU usage of a given VM. None if unable to compute it (as delta are required)
        ----------

        Parameters
        ----------
        vm : DomainEntity
           VM to consider

        Returns
        -------
        cpu_usage : float
            Usage as [0;1]
        """
        virDomain = self.conn.lookupByUUIDString(vm.get_uuid())
        epoch_ns = time.time_ns()
        try:
            stats = virDomain.getCPUStats(total=True)
        except libvirt.libvirtError as ex:  # VM is not alived
            raise ConsumerNotAlived()
        total, system, user = (stats[0]['cpu_time'], stats[0]['system_time'], stats[0]['user_time'])
        cpu_usage_norm = None
        if vm.has_time(): # Compute delta
            prev_epoch, prev_total, prev_system, prev_user = vm.get_time()
            cpu_usage = (total-prev_total)/(epoch_ns-prev_epoch)
            cpu_usage_norm = cpu_usage / vm.get_cpu()
            if cpu_usage_norm>1: cpu_usage_norm = 1
        vm.set_time(epoch_ns=epoch_ns,total=total, system=system, user=user)
        return cpu_usage_norm

    def get_usage_mem(self, vm : DomainEntity):
        """Return the latest Mem usage of a given VM
        ----------

        Parameters
        ----------
        vm : DomainEntity
           VM to consider

        Returns
        -------
        cpu_usage : float
            Usage as [0;1]
        """
        virDomain = self.conn.lookupByUUIDString(vm.get_uuid())
        try:
            stats = virDomain.memoryStats()
        except libvirt.libvirtError as ex:  # VM is not alived
            raise ConsumerNotAlived()
        #keys = ['actual', 'available', 'rss', 'major_fault']
        usage = stats['rss']/stats['actual']
        if usage>1: return 1
        return usage

    def __del__(self):
        """Clean up actions
        ----------
        """
        self.conn.close()

class ConsumerNotAlived(Exception):
    pass