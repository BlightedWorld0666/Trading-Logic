"""Owner-only Discord control and queued operational alerts. No real orders."""
import argparse
import asyncio
import json
from pathlib import Path
from scout.account import Account
from scout.operations import recap
from server_manager import rpc
from scout.board import Board
from scout.safety import Alerts, authorized, control, monitor


def load_config(path):
    config=json.loads(Path(path).read_text())
    if not isinstance(config,dict) or set(config)!={'token','owner_id','guild_id','alerts_channel_id'}:
        raise ValueError('Discord config must contain token, owner_id, guild_id and alerts_channel_id.')
    for key in ('owner_id','guild_id','alerts_channel_id'):
        if not isinstance(config[key],str) or not config[key].isdigit() or len(config[key])>20 or int(config[key])<=0:
            raise ValueError('Enter Discord IDs as positive digit strings.')
    if not isinstance(config['token'],str) or not 30<=len(config['token'])<=200 or config['token'].startswith('ENTER_'):
        raise ValueError('Enter the bot token locally in secrets/discord.json.')
    return config


def build_client(config,account_path,alerts_path,board_path):
    import discord
    from discord import app_commands
    class OwnerTree(app_commands.CommandTree):
        async def interaction_check(self,interaction):
            if authorized(interaction.user.id,interaction.guild_id,config):return True
            await interaction.response.send_message('Owner-only controls in the configured server.',ephemeral=True)
            return False
    class Client(discord.Client):
        def __init__(self):
            super().__init__(intents=discord.Intents.none(),allowed_mentions=discord.AllowedMentions.none())
            self.tree=OwnerTree(self);self.supervisor=None;self.ever_ready=False;self.delivery_ok=False
        async def setup_hook(self):
            self.tree.copy_global_to(guild=discord.Object(id=int(config['guild_id'])))
            await self.tree.sync(guild=discord.Object(id=int(config['guild_id'])))
            self.supervisor=asyncio.create_task(self.watch())
        async def on_ready(self):
            self.ever_ready=True
            # Delivery is healthy only after a successful channel/delivery check.
        async def on_disconnect(self):
            self.delivery_ok=False
            await asyncio.to_thread(Alerts(alerts_path).heartbeat,False)
            if self.ever_ready and Path(account_path).is_file():
                try:await asyncio.to_thread(Account(account_path).trip,'discord_disconnected')
                except Exception:pass  # independent watchdog keeps checking account availability
        async def watch(self):
            while not self.is_closed():
                try:
                    await asyncio.to_thread(Alerts(alerts_path).heartbeat,self.is_ready() and self.delivery_ok)
                    await asyncio.to_thread(monitor,account_path,alerts_path)
                    if self.is_ready():
                        alerts=Alerts(alerts_path)
                        channel=await self.fetch_channel(int(config['alerts_channel_id']))
                        if getattr(channel,'guild',None) is None or channel.guild.id!=int(config['guild_id']):
                            raise ValueError('Alert channel is outside the configured server.')
                        delivery_failed=False
                        for item in await asyncio.to_thread(alerts.pending):
                            try:
                                await channel.send(f"<@{config['owner_id']}> [{item['kind']}] {item['message']}",allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=int(config['owner_id']))]))
                                await asyncio.to_thread(alerts.outcome,item['id'])
                            except Exception as exc:
                                await asyncio.to_thread(alerts.outcome,item['id'],type(exc).__name__)
                                delivery_failed=True
                                await asyncio.to_thread(alerts.heartbeat,False)
                                await asyncio.to_thread(Account(account_path).trip,'discord_disconnected')
                                break
                        self.delivery_ok=not delivery_failed
                        await asyncio.to_thread(alerts.heartbeat,self.delivery_ok)
                except Exception as exc:
                    self.delivery_ok=False
                    try:
                        await asyncio.to_thread(Alerts(alerts_path).heartbeat,False)
                        if Path(account_path).is_file():await asyncio.to_thread(Account(account_path).trip,'discord_disconnected')
                    except Exception:pass
                    print('Discord/safety check:',type(exc).__name__,flush=True)
                await asyncio.sleep(5)
        async def close(self):
            if self.supervisor:
                self.supervisor.cancel()
                try:await self.supervisor
                except asyncio.CancelledError:pass
            await super().close()
    client=Client()
    async def reply(interaction,operation):
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            text=await asyncio.to_thread(operation)
            await interaction.followup.send(str(text)[:1900],ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            message=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
            await interaction.followup.send('Operation failed: '+message[:500],ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
    def status():
        r=monitor(account_path,alerts_path)
        if r.get('configured') is False:return 'Account not configured.'
        s=r['state']
        return json.dumps({'mode':'paper_only','safety':s['safety'],'paused':s['paused'],'drawdown_halted':s['halted'],'worker_active':r['worker_active'],'receipt_fresh':r['receipt_fresh'],'equity':s['equity'],'positions':s['positions'],'pending_alerts':Alerts(alerts_path).snapshot()['pending']},indent=2)
    @client.tree.command(name='trading_status',description='Read paper account, safety and alert status')
    async def trading_status(interaction:discord.Interaction):await reply(interaction,status)
    @client.tree.command(name='trading_control',description='Kill, acknowledge, pause or resume the paper account')
    @app_commands.choices(action=[app_commands.Choice(name=s,value=s) for s in ('kill','acknowledge','pause','resume')])
    async def trading_control(interaction:discord.Interaction,action:app_commands.Choice[str]):
        def operate():
            control(account_path,action.value,alerts_path)
            return status()+'\nAcknowledgement retains pause; resume is a separate command. Drawdown halts remain.'
        await reply(interaction,operate)
    @client.tree.command(name='agent_board',description='Read the latest local research discussion')
    async def agent_board(interaction:discord.Interaction):
        def read():
            threads=Board(board_path).snapshot()['threads']
            if not threads:return 'No discussions yet.'
            t=threads[0]
            return '#'+str(t['id'])+' '+t['title']+' / '+t['status']+'\n'+'\n'.join(m['author']+': '+m['content'].get('summary','') for m in t['messages'][-4:])
        await reply(interaction,read)
    @client.tree.command(name='agent_note',description='Post a local research note; no execution authority')
    async def agent_note(interaction:discord.Interaction,text:str,thread_id:int=0):
        await reply(interaction,lambda:'Saved in discussion #'+str(Board(board_path).human_post(text,thread_id or None)))
    @client.tree.command(name='server_status',description='Read manager-owned service status')
    async def server_status(interaction:discord.Interaction):
        await reply(interaction,lambda:json.dumps(rpc(Path(__file__).resolve().parent),indent=2))
    @client.tree.command(name='server_control',description='Control a fixed manager-owned service')
    @app_commands.choices(service=[app_commands.Choice(name=s,value=s) for s in ('ollama','watchdog','worker','discord','dashboard')],action=[app_commands.Choice(name=s,value=s) for s in ('start','stop','restart')])
    async def server_control(interaction:discord.Interaction,service:app_commands.Choice[str],action:app_commands.Choice[str]):
        await reply(interaction,lambda:json.dumps(rpc(Path(__file__).resolve().parent,action.value,service.value),indent=2))
    @client.tree.command(name='paper_recap',description='Read the current paper recap')
    async def paper_recap(interaction:discord.Interaction):await reply(interaction,lambda:recap(account_path,alerts_path))
    @client.tree.command(name='backup_now',description='Create a private verified backup through the manager')
    async def backup_now(interaction:discord.Interaction):
        await reply(interaction,lambda:'Backup created: '+rpc(Path(__file__).resolve().parent,'backup')['id'])
    return client


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path('secrets/discord.json'))
    p.add_argument('--db',type=Path,default=Path('runtime/demo.sqlite'))
    p.add_argument('--alerts-db',type=Path,default=Path('runtime/alerts.sqlite'))
    p.add_argument('--board-db',type=Path,default=Path('runtime/board.sqlite'))
    args=p.parse_args()
    try:
        config=load_config(args.config)
        Alerts(args.alerts_db).heartbeat(False)
        client=build_client(config,args.db,args.alerts_db,args.board_db)
        client.run(config['token'],log_handler=None)
    except Exception as exc:p.exit(1,'Discord control stopped: '+type(exc).__name__+'. Check local config, dependency installation and permissions.\n')

if __name__=='__main__':main()
