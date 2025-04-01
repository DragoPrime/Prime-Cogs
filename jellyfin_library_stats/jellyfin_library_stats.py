import discord
from redbot.core import commands, Config, app_commands
import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta

# Logging configuration
log = logging.getLogger("red.jellyfinlibs")

class JellyfinLibraryStats(commands.Cog):
    """Cog for monitoring Jellyfin library statistics"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=12843972494, force_registration=True)
        
        # Persistent configuration for Jellyfin
        self.config.register_global(
            jellyfin_url=None,
            jellyfin_api_key=None,
            update_channel_id=None,
            update_message_id=None,
            last_update=None
        )
        
        # Update task
        self.update_task = None

    @commands.group(name="jellyfinstats")
    @commands.admin()
    async def jellyfin_stats(self, ctx):
        """Commands for configuring Jellyfin statistics"""
        if not ctx.invoked_subcommand:
            # Display current configuration
            url = await self.config.jellyfin_url()
            channel_id = await self.config.update_channel_id()
            
            if url and channel_id:
                await ctx.send(f"Current configuration:\n"
                               f"Jellyfin URL: {url}\n"
                               f"Update channel: <#{channel_id}>")
            else:
                await ctx.send("No saved configuration. Use !jellyfinstats setup to configure.")

    @jellyfin_stats.command(name="setup")
    async def setup_jellyfin_stats(self, ctx, jellyfin_url: str, api_key: str, channel: discord.TextChannel):
        """Configure Jellyfin URL, API key, and update channel"""
        # Make sure URL ends without slash
        if jellyfin_url.endswith("/"):
            jellyfin_url = jellyfin_url[:-1]
            
        # Save configuration
        await self.config.jellyfin_url.set(jellyfin_url)
        await self.config.jellyfin_api_key.set(api_key)
        await self.config.update_channel_id.set(channel.id)
        
        # Send initial message to be updated
        message = await channel.send("Updating Freia library statistics...")
        await self.config.update_message_id.set(message.id)

        # Try to test the connection
        success = await self.test_connection()
        if success:
            await ctx.send("Connection to Jellyfin has been tested and works!")
        else:
            await ctx.send("⚠️ Configuration saved, but the connection test failed. Check URL and API key.")
        
        # Trigger immediate update
        await self.update_stats(force_update=True)
        await ctx.send("Jellyfin stats configuration completed!")

    @jellyfin_stats.command(name="test")
    async def test_api(self, ctx):
        """Test connection to Jellyfin API"""
        success = await self.test_connection()
        if success:
            await ctx.send("✅ Connection to Jellyfin is working correctly!")
        else:
            await ctx.send("❌ Connection to Jellyfin failed. Check URL and API key.")

    @jellyfin_stats.command(name="debug")
    async def debug_api(self, ctx):
        """Display debug information about the API"""
        jellyfin_url = await self.config.jellyfin_url()
        api_key = await self.config.jellyfin_api_key()
        
        if not jellyfin_url or not api_key:
            return await ctx.send("No saved configuration.")
        
        debug_info = []
        debug_info.append(f"**Jellyfin URL**: {jellyfin_url}")
        debug_info.append(f"**API Key** (first 4 characters): {api_key[:4]}...")
        
        # Test endpoint for libraries
        async with aiohttp.ClientSession() as session:
            headers = {"X-Emby-Token": api_key}
            
            # Test for /System/Info
            try:
                url = f"{jellyfin_url}/System/Info"
                debug_info.append(f"\n**Testing endpoint**: `{url}`")
                async with session.get(url, headers=headers) as response:
                    debug_info.append(f"Status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        debug_info.append(f"Jellyfin Version: {data.get('Version', 'N/A')}")
                    else:
                        debug_info.append("❌ Error accessing server information")
            except Exception as e:
                debug_info.append(f"❌ Exception: {str(e)}")
            
            # Test for /Library/MediaFolders
            try:
                url = f"{jellyfin_url}/Library/MediaFolders"
                debug_info.append(f"\n**Testing endpoint**: `{url}`")
                async with session.get(url, headers=headers) as response:
                    debug_info.append(f"Status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        items = data.get('Items', [])
                        debug_info.append(f"Number of libraries: {len(items)}")
                        for item in items:
                            debug_info.append(f"- ID: {item.get('Id')}, Name: {item.get('Name')}")
                    else:
                        debug_info.append("❌ Error accessing libraries")
            except Exception as e:
                debug_info.append(f"❌ Exception: {str(e)}")
        
        await ctx.send("\n".join(debug_info))

    @jellyfin_stats.command(name="update")
    async def manual_update(self, ctx):
        """Manually update statistics"""
        await ctx.send("Starting manual update...")
        success = await self.update_stats(force_update=True)
        if success:
            await ctx.send("✅ Statistics manually updated!")
        else:
            await ctx.send("❌ Manual update failed. Check logs for details.")

    async def test_connection(self):
        """Test if connection to Jellyfin works"""
        jellyfin_url = await self.config.jellyfin_url()
        api_key = await self.config.jellyfin_api_key()

        if not jellyfin_url or not api_key:
            return False

        headers = {"X-Emby-Token": api_key}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{jellyfin_url}/System/Info", headers=headers) as response:
                    if response.status == 200:
                        log.info("Connection to Jellyfin tested successfully!")
                        return True
                    else:
                        log.error(f"Connection to Jellyfin failed: Status {response.status}")
                        return False
        except Exception as e:
            log.error(f"Exception when testing Jellyfin connection: {e}")
            return False

    async def fetch_jellyfin_libraries(self):
        """Fetch library information from Jellyfin server"""
        jellyfin_url = await self.config.jellyfin_url()
        api_key = await self.config.jellyfin_api_key()

        if not jellyfin_url or not api_key:
            log.error("URL or API key not configured")
            return None

        headers = {"X-Emby-Token": api_key}

        try:
            async with aiohttp.ClientSession() as session:
                # Fetch list of libraries
                log.info(f"Fetching libraries from {jellyfin_url}/Library/MediaFolders")
                async with session.get(f"{jellyfin_url}/Library/MediaFolders", headers=headers) as libraries_response:
                    log.info(f"Response status: {libraries_response.status}")
                    
                    if libraries_response.status == 200:
                        libraries_data = await libraries_response.json()
                        libraries = libraries_data.get('Items', [])
                        log.info(f"Number of libraries found: {len(libraries)}")
                        
                        # Collect statistics for each library
                        library_stats = {}
                        for library in libraries:
                            library_id = library.get('Id')
                            library_name = library.get('Name')
                            
                            # Ignore Playlists library
                            if "playlist" in library_name.lower():
                                log.info(f"Ignoring library: {library_name} (is playlist)")
                                continue
                            
                            log.info(f"Processing library: {library_name} (ID: {library_id})")
                            
                            # Check collection type
                            collection_type = library.get('CollectionType', '').lower()
                            
                            # Use the Items endpoint with correct parameters
                            try:
                                items_url = ""
                                if "tvshows" in collection_type or "tv" in collection_type:
                                    # For TV libraries, count only series, not episodes
                                    items_url = f"{jellyfin_url}/Items?ParentId={library_id}&IncludeItemTypes=Series&Recursive=true&Limit=0"
                                    log.info(f"TV library detected, counting series: {items_url}")
                                else:
                                    # For other types, use standard behavior
                                    items_url = f"{jellyfin_url}/Items?ParentId={library_id}&Recursive=true&Limit=0"
                                    log.info(f"Standard library: {items_url}")
                                
                                async with session.get(items_url, headers=headers) as items_response:
                                    log.info(f"Items response status: {items_response.status}")
                                    
                                    if items_response.status == 200:
                                        items_data = await items_response.json()
                                        total_records = items_data.get('TotalRecordCount', 0)
                                        log.info(f"Total records in {library_name}: {total_records}")
                                        library_stats[library_name] = total_records
                                    else:
                                        log.error(f"Error accessing items from library {library_name}: {items_response.status}")
                                        library_stats[library_name] = 0
                            except Exception as e:
                                log.error(f"Exception getting count for library {library_name}: {e}")
                                library_stats[library_name] = 0
                        
                        if library_stats:
                            log.info(f"Stats collected successfully: {library_stats}")
                            return library_stats
                        else:
                            log.error("No statistics found")
                            return None
                    else:
                        log.error(f"Error accessing libraries: {libraries_response.status}")
                        return None
        except Exception as e:
            log.error(f"General exception fetching libraries: {e}")
            return None

    async def update_stats(self, force_update=False):
        """Update message with library statistics"""
        # Check if all necessary elements are configured
        jellyfin_url = await self.config.jellyfin_url()
        channel_id = await self.config.update_channel_id()
        message_id = await self.config.update_message_id()
        
        if not all([jellyfin_url, channel_id, message_id]):
            log.error("Configuration is not complete")
            return False

        try:
            # Fetch library statistics
            log.info("Starting statistics update")
            library_stats = await self.fetch_jellyfin_libraries()

            if library_stats:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    log.error(f"Channel {channel_id} not found")
                    return False
                
                # Build statistics message
                embed = discord.Embed(
                    title="📊 Freia Library Statistics",
                    description=f"Updated at: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                    color=discord.Color.blue()
                )
                
                # Add statistics for each library
                for library_name, item_count in library_stats.items():
                    embed.add_field(name=library_name, value=str(item_count), inline=False)

                # Update message - specify content="" to clear original text
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(content="", embed=embed)
                    log.info("Message updated successfully")
                except discord.NotFound:
                    log.error(f"Message {message_id} not found")
                    return False
                except Exception as e:
                    log.error(f"Error updating message: {e}")
                    return False

                # Save last update date
                await self.config.last_update.set(datetime.now().isoformat())
                return True
            else:
                log.error("Could not fetch library statistics")
                return False

        except Exception as e:
            log.error(f"General error updating statistics: {e}")
            return False

    async def background_update(self):
        """Background task for weekly updates"""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                # Update once every 7 days (weekly)
                log.info("Starting weekly update")
                await self.update_stats()
                await asyncio.sleep(604800)  # 7 days (7 * 24 * 60 * 60 = 604800 seconds)
            except Exception as e:
                log.error(f"Error in background task: {e}")
                await asyncio.sleep(3600)  # Wait one hour in case of error

    def cog_unload(self):
        """Stop task when cog is unloaded"""
        if self.update_task:
            self.update_task.cancel()

    async def cog_load(self):
        """Start update task when cog is loaded"""
        log.info("Jellyfin Library Stats cog loaded")
        # Start initial update
        await self.update_stats(force_update=True)
        
        # Start background task for weekly updates
        self.update_task = self.bot.loop.create_task(self.background_update())
