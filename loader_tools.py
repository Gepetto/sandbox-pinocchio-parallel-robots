import pinocchio as pin
from pinocchio.robot_wrapper import RobotWrapper
import re
import yaml
from yaml.loader import SafeLoader
from warnings import warn
import numpy as np

from actuation_model import ActuationModel

def nameFrameConstraint(model, nomferme="fermeture", Lid=[]):
    """
    nameFrameConstraint(model, nomferme="fermeture", Lid=[])

    Takes a robot model and returns a list of frame names that are constrained to be in contact: Ln=[['name_frame1_A','name_frame1_B'],['name_frame2_A','name_frame2_B'].....]
    where names_frameX_A and names_frameX_B are the frames in forced contact by the kinematic loop.
    The frames must be named: "...nomfermeX_..." where X is the number of the corresponding kinematic loop.
    The kinematics loop can be selectionned with Lid=[id_kinematcsloop1, id_kinematicsloop2 .....] = [1,2,...]
    if Lid = [] all the kinematics loop will be treated.

    Argument:
        model - Pinocchio robot model
        nom_ferme - nom de la fermeture  
        Lid - List of kinematic loop indexes to select
    Return:
        Lnames - List of frame names that should be in contact
    """
    warn("nameFrameConstraint depreceated")
    if Lid == []:
        Lid = range(len(model.frames) // 2)
    Lnames = []
    for id in Lid:
        pair_names = []
        for f in model.frames:
            name = f.name
            match = re.search(nomferme + str(id), name)
            match2 = re.search("frame", f.name)
            if match and not (match2):
                pair_names.append(name)
        if len(pair_names) == 2:
            Lnames.append(pair_names)
    return Lnames

def jointTypeUpdate(model, rotule_name="to_rotule"):
    """
    model = jointTypeUpdate(model,rotule_name="to_rotule")
    Takes a robot model and change joints whose name contains rotule_name to rotule joint type. 
    
    Argument:
        model - Pinocchio robot model
    Return:
        new_model - Updated robot model
    """
    warn("Function 'jointTypeUpdate' is depreceated - prefer using a YAML file as complement to the URDF")
    new_model = pin.Model() 
    first = True
    i = 0
    for jp, iner, name, i, j in zip(
        model.jointPlacements, model.inertias, model.names, model.parents,model.joints
    ):
        if first:
            first = False
        else:
            match = re.search(rotule_name, name)

            if match:
                jm = pin.JointModelSpherical()
            else:
                jm = j
            jid = new_model.addJoint(i, jm, jp, name)
            new_model.appendBodyToJoint(jid, iner, pin.SE3.Identity())

    for frame in model.frames:
        name = frame.name
        parent_joint = frame.parentJoint
        placement = frame.placement
        frame = pin.Frame(name, parent_joint, placement, pin.BODY)
        _ = new_model.addFrame(frame, False)

    return(new_model)

def generateYAML(path):
    """
    if robot.urdf inside the path, write a yaml file associate to the the robot.
    Write the name of the frame constrained, the type of the constraint, the presence of rotule articulation, 
    the name of the motor, idq and idv (with the sphrical joint).
    """
    # ! It is using old functions to write the yaml, I would prefer changing this function and removing deprecated functions
    name_mot="mot"
    name_rotule="to_rotule" 
    rob = RobotWrapper.BuildFromURDF(path + "/robot.urdf", path)
    model=jointTypeUpdate(rob.model,name_rotule)
    Ljoint=[]
    Ltype=[]
    Lmot=[]
    for name in model.names:
        match = re.search(name_rotule, name)
        match_mot= re.search(name_mot,name)
        if match :
            Ljoint.append(name)
            Ltype.append("SPHERICAL")
        if match_mot:
            Lmot.append(name)

    name_frame_constraint=nameFrameConstraint(model, nomferme="fermeture")
    constraint_type=["6d"]*len(name_frame_constraint)

    with open(path + '/robot.yaml', 'w') as f:
        f.write('closed_loop: '+ str(name_frame_constraint)+'\n')
        f.write('type: '+str(constraint_type)+'\n')
        f.write('name_mot: '+str(Lmot)+'\n')
        f.write('joint_name: '+str(Ljoint)+'\n')
        f.write('joint_type: '+str(Ltype)+'\n')

def getYAMLcontents(path, name_yaml='robot.yaml'):
    with open(path+"/"+name_yaml, 'r') as yaml_file:
        contents = yaml.load(yaml_file, Loader=SafeLoader)
    return(contents)

def completeRobotLoader(path,name_urdf="robot.urdf",name_yaml="robot.yaml"):
    """
    Return  model and constraint model associated to a directory, where the name od the urdf is robot.urdf and the name of the yam is robot.yaml
    if no type assiciated, 6D type is applied
    """
    # Load the robot model using the pinocchio URDF parser
    robot = RobotWrapper.BuildFromURDF(path + "/" + name_urdf, path)
    model = robot.model

    yaml_content = getYAMLcontents(path, name_yaml)

    # try to update model
    update_joint = yaml_content['joint_name']   
    joints_types = yaml_content['joint_type']
    LjointFixed=[]
    new_model = pin.Model() 
    visual_model = robot.visual_model
    for place, iner, name, parent, joint in list(zip(model.jointPlacements, model.inertias, model.names, model.parents,model.joints))[1:]:
        if name in update_joint:
            joint_type = joints_types[update_joint.index(name)]
            if joint_type=='SPHERICAL':
                jm = pin.JointModelSpherical()
            if joint_type=="FIXED":
                jm = joint
                LjointFixed.append(joint.id)
        else:
            jm = joint
        jid = new_model.addJoint(parent, jm, place, name)
        new_model.appendBodyToJoint(jid, iner, pin.SE3.Identity())
    
    for frame in model.frames:
        # I am pretty sure I can remove the next 4 lines
        name = frame.name
        parent_joint = frame.parentJoint
        placement = frame.placement
        frame = pin.Frame(name, parent_joint, placement, frame.type)
        new_model.addFrame(frame, False)

    new_model.frames.__delitem__(0)
    new_model, visual_model = pin.buildReducedModel(new_model,visual_model,LjointFixed,pin.neutral(new_model))

    model = new_model

    #check if type is associated,else 6D is used
    try :
        name_frame_constraint = yaml_content['closed_loop']
        try :
            constraint_type = yaml_content['type']
        except :
            constraint_type = ["6D"]*len(name_frame_constraint)
    
        #construction of constraint model
        Lconstraintmodel = []
        for L,ctype in zip(name_frame_constraint, constraint_type):
            name1 = L[0]
            name2 = L[1]
            id1 = model.getFrameId(name1)
            id2 = model.getFrameId(name2)
            Se3joint1 = model.frames[id1].placement
            Se3joint2 = model.frames[id2].placement
            parentjoint1 = model.frames[id1].parentJoint
            parentjoint2 = model.frames[id2].parentJoint
            if ctype=="3D" or ctype=="3d":
                constraint = pin.RigidConstraintModel(
                    pin.ContactType.CONTACT_3D,
                    model,
                    parentjoint1,
                    Se3joint1,
                    parentjoint2,
                    Se3joint2,
                    pin.ReferenceFrame.LOCAL,
                )
                constraint.name = name1+"C"+name2
            else :
                constraint = pin.RigidConstraintModel(
                    pin.ContactType.CONTACT_6D,
                    model,
                    parentjoint1,
                    Se3joint1,
                    parentjoint2,
                    Se3joint2,
                    pin.ReferenceFrame.LOCAL,
                )
                constraint.name = name1+"C"+name2
            Lconstraintmodel.append(constraint)
        
        constraint_models = Lconstraintmodel
    except:
        print("no constraint")

    actuation_model = ActuationModel(model,yaml_content['name_mot'])
    return(model, constraint_models, actuation_model, visual_model)


def getRobotInfo(path):
    """
    Dont semms usefull anymore with completeModelFromDirectory(path)


    (name__closedloop, name_mot, number_closedloop, type) = getRobotInfo(path)
    Returns information stored in the YAML file at path 'path/robot.yaml'. If no YAML file is found, default values are returned.
    
    Arguments:  
        path - path to the directory contained the YAML info file
    Return:
        Tuple containing the info extracted
    """
    warn("getRobotInfo depreceated")
    try:
        with open(path+"/robot.yaml", 'r') as yaml_file:
            yaml_content = yaml.load(yaml_file, Loader=SafeLoader)
            name_closedloop = yaml_content["name_closedloop"]
            name_mot = yaml_content["name_mot"]
            type = yaml_content["type"]
        try:
            number_closedloop = yaml_content["closed_loop_number"]
        except:
            number_closedloop = -1

    except:
        warn("no robot.yaml found, default value applied")
        name_closedloop = "fermeture"
        name_mot = "mot"
        number_closedloop = -1
        type = "6D"
    return (name_closedloop, name_mot, number_closedloop, type)


def getSimplifiedRobot(path):
    """
    robot = getSimplifiedRobot(path)
    Loads a robot and builds a reduced model from the yaml file info

    Argument:
        path - the dir of the file that contain the urdf file & the stl files
    Return:
        rob - The simplified robot
    
    load a robot with N closed loop with a joint on each of the 2 branch that are closed, return a simplified model of the robot where one of this joint is fixed
    """
    warn("getsimplifiedRobot depreceated")
    # TODO we should here reuse the previous function, no point in doing this again
    try:
        yaml_file = open(path+"/robot.yaml", 'r')
        yaml_content = yaml.load(yaml_file)
        name_closedloop = yaml_content["name_closedloop"]
        name_mot = yaml_content["name_mot"]
    except:
        warn("no robot.yaml found, default value applied")
        name_closedloop = "fermeture"
        name_mot = "mot"

    rob = RobotWrapper.BuildFromURDF(path + "/robot.urdf", path)
    Lid = []
    # to simplifie the conception, the two contact point are generate with a joint
    # supression of one of this joint :
    for (joint, id) in zip(rob.model.names, range(len(rob.model.names))):
        match = re.search(name_closedloop, joint)
        match2 = re.search("B", joint)
        if match and match2:
            Lid.append(id)

    rob.model, rob.visual_model = pin.buildReducedModel(
        rob.model, rob.visual_model, Lid, np.zeros(rob.nq)
    )
    rob.data = rob.model.createData()
    rob.q0 = np.zeros(rob.nq)
    return rob


def getConstraintModelFromName(model, Lnjoint, ref=pin.ReferenceFrame.LOCAL, const_type=pin.ContactType.CONTACT_6D):
    """
    getconstraintModelfromname(model,Lnjoint,ref=pin.ReferenceFrame.LOCAL):

    Takes a robot model and Lnjoint=[['name_joint1_A','name_joint1_B'],['name_joint2_A','name_joint2_B'].....]
    Returns the list of the constraintmodel where joint1A is in contact with joint1_B, joint2_A in contact with joint2_B etc

    Argument:
        model - Pinocchio robot model
        Lnjoint - List of frame names to should be in contact (As generated by nameFrameConstraint) 
        ref - Reference frame from pinocchio, should be pin.ReferenceFrame.{LOCAL, WORLD, LOCAL_WORLD_ALIGNED}
        const_type - Type of constraint to usem should be pin.ContactType.{CONTACT_6D, CONTACT_3D}
    Return:
        Lconstraintmodel - List of corresponding pinocchio constraint models
    """
    Lconstraintmodel = []
    for L in Lnjoint:
        name1 = L[0]
        name2 = L[1]
        id1 = model.getFrameId(name1)
        id2 = model.getFrameId(name2)
        Se3joint1 = model.frames[id1].placement
        Se3joint2 = model.frames[id2].placement
        parentjoint1 = model.frames[id1].parentJoint
        parentjoint2 = model.frames[id2].parentJoint
        constraint = pin.RigidConstraintModel(
            const_type,
            model,
            parentjoint1,
            Se3joint1,
            parentjoint2,
            Se3joint2,
            ref,
        )
        constraint.name = name1[:-2]
        Lconstraintmodel.append(constraint)
    return Lconstraintmodel

def jointTypeUpdate(model, rotule_name="to_rotule"):
    """
    model = jointTypeUpdate(model,rotule_name="to_rotule")
    Takes a robot model and change joints whose name contains rotule_name to rotule joint type. 
    
    Argument:
        model - Pinocchio robot model
    Return:
        new_model - Updated robot model
    """
    warn("jointTypeUpdate depreceated")
    new_model = pin.Model() 
    first = True
    i = 0
    for jp, iner, name, i, j in zip(
        model.jointPlacements, model.inertias, model.names, model.parents,model.joints
    ):
        if first:
            first = False
        else:
            match = re.search(rotule_name, name)

            if match:
                jm = pin.JointModelSpherical()
            else:
                jm = j
            jid = new_model.addJoint(i, jm, jp, name)
            new_model.appendBodyToJoint(jid, iner, pin.SE3.Identity())

    for frame in model.frames:
        name = frame.name
        parent_joint = frame.parentJoint
        placement = frame.placement
        frame = pin.Frame(name, parent_joint, placement, pin.BODY)
        _ = new_model.addFrame(frame, False)

    return(new_model)

import unittest
class TestRobotLoader(unittest.TestCase):
    def test_complete_loader(self):
        import io
        robots_paths = [['robot_simple_iso3D', 'unittest_iso3D.txt'],
                        ['robot_simple_iso6D', 'unittest_iso6D.txt']]

        for rp in robots_paths:
            path = "robots/"+rp[0]
            m ,cm, am, vm = completeRobotLoader(path)
            joints_info = [(j.id, j.shortname(), j.idx_q, j.idx_v) for j in m.joints[1:]]
            frames_info = [(f.name, f.inertia, f.parentJoint, f.parentFrame, f.type) for f in m.frames]
            constraint_info = [(cmi.name, cmi.joint1_id, cmi.joint2_id, cmi.joint1_placement, cmi.joint2_placement, cmi.type) for cmi in cm]
            mot_info = [(am.idqfree, am.idqmot, am.idvfree, am.idvmot)]
            
            results = io.StringIO()
            results.write('\n'.join(f'{x[0]} {x[1]} {x[2]} {x[3]}' for x in joints_info))
            results.write('\n'.join(f'{x[0]} {x[1]} {x[2]} {x[3]} {x[4]}' for x in frames_info))
            results.write('\n'.join(f'{x[0]} {x[1]} {x[2]} {x[3]} {x[4]} {x[5]}' for x in constraint_info))
            results.write('\n'.join(f'{x[0]} {x[1]} {x[2]} {x[3]}' for x in mot_info))
            results.seek(0)

            # Ground truth is defined from a known good result
            with open('unittest/'+rp[1], 'r') as truth:
                assert truth.read() == results.read()
        
if __name__ == "__main__":
    unittest.main()
