"""Fresh, synthetic desktop/browser database and read-only copies for F01–F14."""
from pathlib import Path
import hashlib,json,shutil,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.seed_legacy_operator_workflows import seed
from tests.test_legacy_fourteen_closure import add_frame
from tests.test_s09_result_migration import source_file
from backend.config import AppConfig
from backend.db import Database
from backend.runtime import Runtime


def seed_fourteen(directory: Path) -> dict:
    result=seed(directory);db=Database(directory/'geospectrum.sqlite3');runtime=Runtime(AppConfig(data_dir=directory),database=db)
    service=runtime.dispersion_service()
    task=service.create_task({'name':'Fourteen calibration','ccd_layout_id':'default','frame_count':2,'dark_frame_count':0,
        'lines':[{'element':element,'wavelength_nm':wave,'ccd_index':ccd,'actual_position':actual}
                 for element,wave,ccd,actual in [('Fe',250.1,0,107),('Cu',260,0,200),('Zn',270,0,300),('Pb',280,1,400)]]})
    for index,a,b in [(0,1000,1),(1,1,900)]:
        values=[1]*task['layout']['points_per_ccd'];values[107]=a;values[117]=b;add_frame(db,task['id'],'burn',index,values)
    with db.write() as connection:connection.execute("UPDATE dispersion_tasks SET status='completed',burn_frames_captured=2 WHERE id=?",(task['id'],))
    result['dispersion_task_id']=task['id'];result['dispersion_fe_id']=task['lines'][0]['id']
    originals=directory/'old-copies';originals.mkdir()
    source=Path(__file__).parent/'fixtures/legacy_runtime'
    for name in ['DIRECT.MTD','DIRECT.CFG','DIRECT.OPT']:shutil.copy2(source/name,originals/name)
    (originals/'DIRECT.CFG').write_text('[ANALYZE]\nRoundDarkTime=12\nWaitTime=1234\nLogAna=1\nLookBand=1\n[IgnitWst]\nPreBurn=5\nBurnCyc=1.25\nBurnCount=9\nBackCount=2\n',encoding='ascii')
    migration=runtime.legacy_migration_service();staged=migration.stage(*(str(originals/name) for name in ['DIRECT.MTD','DIRECT.CFG','DIRECT.OPT']),None)
    migration.commit(staged['id'],None);result['migration_run_id']=staged['id']
    pdt=originals/'old.pdt';shutil.copy2(source_file('pdt'),pdt)
    migration=runtime.result_migration_service();staged=migration.stage(str(pdt),None);migration.commit(staged['id'],None)
    with db.read() as connection:result['pdt_id']=connection.execute("SELECT id FROM result_matrices WHERE format='pdt' ORDER BY id DESC LIMIT 1").fetchone()[0]
    result['original_copies']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in originals.iterdir()}
    (directory/'operator-fixture.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':print(json.dumps(seed_fourteen(Path(sys.argv[1])),ensure_ascii=False))
