import uuid
import requests
from bot import asyncio, os, time
from bot.config import conf
from bot.utils.bot_utils import Qbit_c, sync_to_async
from bot.utils.log_utils import log, logger


class JDownloaderClient:
    """JDownloader API client wrapper"""
    
    def __init__(self, host="localhost", port=3129):
        self.base_url = f"http://{host}:{port}"
        self.session = requests.Session()
    
    def _request(self, endpoint, method="GET", data=None):
        """Make API request to JDownloader"""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                response = self.session.get(url, timeout=30)
            elif method == "POST":
                response = self.session.post(url, json=data, timeout=30)
            response.raise_for_status()
            return response.json() if response.text else None
        except Exception as e:
            log(f"JD API Error: {e}")
            return None
    
    def add_links(self, links, download_path=None, package_name=None):
        """Add download links to JDownloader"""
        data = {
            "links": links if isinstance(links, list) else [links],
            "packageName": package_name or str(uuid.uuid4()),
            "destinationFolder": download_path or f"{os.getcwd()}/downloads"
        }
        return self._request("/linkgrabberv2/addLinks", method="POST", data=data)
    
    def get_download_info(self, package_uuid):
        """Get download information by package UUID"""
        data = {"packageUUIDs": [package_uuid]}
        return self._request("/downloadsV2/queryPackages", method="POST", data=data)
    
    def get_link_info(self, link_uuid):
        """Get link information"""
        data = {"linkUUIDs": [link_uuid]}
        return self._request("/downloadsV2/queryLinks", method="POST", data=data)
    
    def start_downloads(self, package_uuid=None):
        """Start downloads"""
        data = {}
        if package_uuid:
            data["packageUUIDs"] = [package_uuid]
        return self._request("/downloadsV2/startDownloads", method="POST", data=data)
    
    def stop_downloads(self, link_uuids):
        """Stop specific downloads"""
        data = {"linkUUIDs": link_uuids if isinstance(link_uuids, list) else [link_uuids]}
        return self._request("/downloadsV2/stopDownloads", method="POST", data=data)
    
    def remove_links(self, link_uuids, delete_files=True):
        """Remove downloads"""
        data = {
            "linkUUIDs": link_uuids if isinstance(link_uuids, list) else [link_uuids],
            "deleteFiles": delete_files
        }
        return self._request("/downloadsV2/removeLinks", method="POST", data=data)
    
    def cleanup_link_collector(self, link_ids, action="DELETE_ALL"):
        """Clean up link collector"""
        data = {
            "linkIds": link_ids if isinstance(link_ids, list) else [link_ids],
            "action": action
        }
        return self._request("/linkgrabberv2/cleanup", method="POST", data=data)
    
    def move_to_downloads(self, link_ids, package_ids):
        """Move links from link grabber to downloads"""
        data = {
            "linkIds": link_ids if isinstance(link_ids, list) else [link_ids],
            "packageIds": package_ids if isinstance(package_ids, list) else [package_ids]
        }
        return self._request("/linkgrabberv2/moveToDownloadlist", method="POST", data=data)
    
    def query_link_collector(self):
        """Query link collector for pending links"""
        return self._request("/linkgrabberv2/queryLinks", method="POST", data={})


def get_jd_client():
    """Get JDownloader client instance"""
    port = getattr(conf, 'JD_PORT', 3129)
    host = getattr(conf, 'JD_HOST', 'localhost')
    return JDownloaderClient(host=host, port=port)


async def rm_jd_download(*link_uuids, jd=None):
    """Remove JDownloader downloads"""
    if not jd:
        jd = get_jd_client()
    for link_uuid in link_uuids:
        try:
            await sync_to_async(jd.remove_links, link_uuid, delete_files=True)
        except Exception:
            log(Exception)


async def get_jd_name(url):
    """Get filename from JDownloader without downloading"""
    jd = get_jd_client()
    dinfo = Qbit_c()
    package_name = "info_" + str(uuid.uuid4())
    
    try:
        # Add link to link collector
        result = await sync_to_async(
            jd.add_links, 
            url, 
            download_path=f"{os.getcwd()}/temp",
            package_name=package_name
        )
        
        if not result:
            dinfo.error = "E404: JDownloader is not available or failed to add link."
            return dinfo
        
        c_time = time.time()
        link_collector_data = None
        
        # Wait for link to appear in collector
        while True:
            if time.time() - c_time > 300:
                dinfo.error = "E408: Getting filename timed out."
                break
            
            links = await sync_to_async(jd.query_link_collector)
            
            if links and len(links) > 0:
                # Find our package
                for link in links:
                    if link.get('packageUUID') == package_name or package_name in str(link.get('comment', '')):
                        link_collector_data = link
                        break
                
                if link_collector_data:
                    name = link_collector_data.get('name')
                    if name and not name.startswith("[METADATA]"):
                        dinfo.name = name
                        dinfo.size = link_collector_data.get('bytesTotal', 0)
                        break
            
            await asyncio.sleep(2)
        
        # Cleanup link collector
        if link_collector_data:
            link_ids = [link_collector_data.get('uuid')]
            await sync_to_async(jd.cleanup_link_collector, link_ids)
            
    except Exception as e:
        dinfo.error = f"JD Error: {str(e)}"
        await logger(Exception)
    finally:
        return dinfo


async def jd_download(url, download_path, tag=None):
    """
    Download file using JDownloader
    Returns download info object
    """
    jd = get_jd_client()
    dinfo = Qbit_c()
    package_name = tag or "jd_" + str(uuid.uuid4())
    
    try:
        # Add link
        result = await sync_to_async(
            jd.add_links,
            url,
            download_path=download_path,
            package_name=package_name
        )
        
        if not result:
            dinfo.error = "E404: JDownloader is not available."
            return dinfo
        
        start_time = time.time()
        package_uuid = None
        link_uuid = None
        
        # Wait for link to be processed
        while True:
            if time.time() - start_time > 120:
                dinfo.error = "E408: Link processing timed out."
                return dinfo
            
            links = await sync_to_async(jd.query_link_collector)
            
            if links and len(links) > 0:
                for link in links:
                    if package_name in str(link.get('comment', '')) or link.get('packageUUID') == package_name:
                        package_uuid = link.get('packageUUID')
                        link_uuid = link.get('uuid')
                        break
                
                if link_uuid:
                    break
            
            await asyncio.sleep(2)
        
        # Move to downloads
        await sync_to_async(jd.move_to_downloads, [link_uuid], [package_uuid])
        
        # Start download
        await sync_to_async(jd.start_downloads, package_uuid)
        
        dinfo.name = package_name
        dinfo.hash = link_uuid  # Store link UUID for tracking
        dinfo.package_uuid = package_uuid
        
        return dinfo
        
    except Exception as e:
        dinfo.error = f"JD Error: {str(e)}"
        await logger(Exception)
        return dinfo


async def get_jd_progress(link_uuid, jd=None):
    """
    Get download progress for JDownloader link
    Returns dict with progress info
    """
    if not jd:
        jd = get_jd_client()
    
    try:
        link_info = await sync_to_async(jd.get_link_info, link_uuid)
        
        if not link_info or len(link_info) == 0:
            return None
        
        info = link_info[0]
        
        progress_data = {
            'name': info.get('name', 'Unknown'),
            'total': info.get('bytesTotal', 0),
            'completed': info.get('bytesLoaded', 0),
            'speed': info.get('speed', 0),
            'status': info.get('status', 'Unknown'),
            'eta': info.get('eta', 0),
            'finished': info.get('finished', False),
            'running': info.get('running', False),
            'enabled': info.get('enabled', False)
        }
        
        return progress_data
        
    except Exception as e:
        await logger(Exception)
        return None


def clean_jd_dl(link_uuid, jd=None):
    """Clean up JDownloader download"""
    if not jd:
        jd = get_jd_client()
    try:
        jd.remove_links(link_uuid, delete_files=True)
    except Exception:
        log(Exception)