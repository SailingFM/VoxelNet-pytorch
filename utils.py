from __future__ import division
import numpy as np
import math
import cv2
from box_overlaps import *
from data_aug import aug_data
import yaml

yamlPath = "configure.yaml"
f = open(yamlPath, 'r', encoding='utf-8')
conf = f.read()
conf_dict = yaml.safe_load(conf) 


range_x=conf_dict['range_x']
range_y=conf_dict['range_y']
range_z=conf_dict['range_z']
vox_depth = conf_dict['vox_d']
vox_width = conf_dict['vox_w']
vox_height = conf_dict['vox_h']
classes = conf_dict['classes'] 
pt_thres_per_vox = conf_dict['pt_thres_per_vox'] 
anchors = conf_dict['anchors']
anchors_per_vox = conf_dict['anchors_per_vox']
pos_threshold = conf_dict['pos_threshold']
neg_threshold = conf_dict['neg_threshold']
H = (max(range_x)-min(range_x))//vox_height
W = (max(range_y)-min(range_y))//vox_width
D = (max(range_z)-min(range_z))//vox_depth
        
def get_filtered_lidar(lidar, boxes3d=None):

    pxs = lidar[:, 0]
    pys = lidar[:, 1]
    pzs = lidar[:, 2]

    filter_x = np.where((pxs >= range_x[0]) & (pxs < range_x[1]))[0]
    filter_y = np.where((pys >= range_y[0]) & (pys < range_y[1]))[0]
    filter_z = np.where((pzs >= range_z[0]) & (pzs < range_z[1]))[0]
    filter_xy = np.intersect1d(filter_x, filter_y)
    filter_xyz = np.intersect1d(filter_xy, filter_z)

    if boxes3d is not None:
        box_x = (boxes3d[:, :, 0] >= range_x[0]) & (boxes3d[:, :, 0] < range_x[1])
        box_y = (boxes3d[:, :, 1] >= range_y[0]) & (boxes3d[:, :, 1] < range_y[1])
        box_z = (boxes3d[:, :, 2] >= range_z[0]) & (boxes3d[:, :, 2] < range_z[1])
        box_xyz = np.sum(box_x & box_y & box_z,axis=1)

        return lidar[filter_xyz], boxes3d[box_xyz>0]

    return lidar[filter_xyz]

def lidar_to_bev(lidar):

    X0, Xn = 0, W
    Y0, Yn = 0, H
    Z0, Zn = 0, D

    width  = Yn - Y0
    height   = Xn - X0
    channel = Zn - Z0  + 2

    pxs = lidar[:, 0]
    pys = lidar[:, 1]
    pzs = lidar[:, 2]
    prs = lidar[:, 3]

    qxs=((pxs-range_x[0])/vox_width).astype(np.int32)
    qys=((pys-range_y[0])/vox_height).astype(np.int32)
    qzs=((pzs-range_z[0])/vox_depth).astype(np.int32)

    print('height,width,channel=%d,%d,%d'%(height,width,channel))
    top = np.zeros(shape=(height,width,channel), dtype=np.float32)
    mask = np.ones(shape=(height,width,channel-1), dtype=np.float32)* -5

    for i in range(len(pxs)):
        top[-qxs[i], -qys[i], -1]= 1+ top[-qxs[i], -qys[i], -1]
        if pzs[i]>mask[-qxs[i], -qys[i],qzs[i]]:
            top[-qxs[i], -qys[i], qzs[i]] = max(0,pzs[i]-range_z[0])
            mask[-qxs[i], -qys[i],qzs[i]]=pzs[i]
        if pzs[i]>mask[-qxs[i], -qys[i],-1]:
            mask[-qxs[i], -qys[i],-1]=pzs[i]
            top[-qxs[i], -qys[i], -2]=prs[i]


    top[:,:,-1] = np.log(top[:,:,-1]+1)/math.log(64)

    if 1:
        # top_image = np.sum(top[:,:,:-1],axis=2)
        density_image = top[:,:,-1]
        density_image = density_image-np.min(density_image)
        density_image = (density_image/np.max(density_image)*255).astype(np.uint8)
        # top_image = np.dstack((top_image, top_image, top_image)).astype(np.uint8)


    return top, density_image


def draw_gt_boxes3d(gt_boxes3d, fig, color=(1,0,0), line_width=2):

    num = len(gt_boxes3d)
    for n in range(num):
        b = gt_boxes3d[n]

        for k in range(0,4):

            i,j=k,(k+1)%4
            mlab.plot3d([b[i,0], b[j,0]], [b[i,1], b[j,1]], [b[i,2], b[j,2]], color=color, tube_radius=None, line_width=line_width, figure=fig)

            i,j=k+4,(k+3)%4 + 4
            mlab.plot3d([b[i,0], b[j,0]], [b[i,1], b[j,1]], [b[i,2], b[j,2]], color=color, tube_radius=None, line_width=line_width, figure=fig)

            i,j=k,k+4
            mlab.plot3d([b[i,0], b[j,0]], [b[i,1], b[j,1]], [b[i,2], b[j,2]], color=color, tube_radius=None, line_width=line_width, figure=fig)

    mlab.view(azimuth=180,elevation=None,distance=50,focalpoint=[ 12.0909996 , -1.04700089, -2.03249991])#2.0909996 , -1.04700089, -2.03249991

def project_velo2rgb(velo,calib):
    T=np.zeros([4,4],dtype=np.float32)
    T[:3,:]=calib['Tr_velo2cam']
    T[3,3]=1
    R=np.zeros([4,4],dtype=np.float32)
    R[:3,:3]=calib['R0']
    R[3,3]=1
    num=len(velo)
    projections = np.zeros((num,8,2),  dtype=np.int32)
    for i in range(len(velo)):
        box3d=np.ones([8,4],dtype=np.float32)
        box3d[:,:3]=velo[i]
        M=np.dot(calib['P2'],R)
        M=np.dot(M,T)
        box2d=np.dot(M,box3d.T)
        box2d=box2d[:2,:].T/box2d[2,:].reshape(8,1)
        projections[i] = box2d
    return projections

def draw_rgb_projections(image, projections, color=(255,255,255), thickness=2, darker=1):

    img = image.copy()*darker
    num=len(projections)
    forward_color=(255,255,0)
    for n in range(num):
        qs = projections[n]
        for k in range(0,4):
            i,j=k,(k+1)%4

            cv2.line(img, (qs[i,0],qs[i,1]), (qs[j,0],qs[j,1]), color, thickness, cv2.LINE_AA)

            i,j=k+4,(k+1)%4 + 4
            cv2.line(img, (qs[i,0],qs[i,1]), (qs[j,0],qs[j,1]), color, thickness, cv2.LINE_AA)

            i,j=k,k+4
            cv2.line(img, (qs[i,0],qs[i,1]), (qs[j,0],qs[j,1]), color, thickness, cv2.LINE_AA)

        cv2.line(img, (qs[3,0],qs[3,1]), (qs[7,0],qs[7,1]), forward_color, thickness, cv2.LINE_AA)
        cv2.line(img, (qs[7,0],qs[7,1]), (qs[6,0],qs[6,1]), forward_color, thickness, cv2.LINE_AA)
        cv2.line(img, (qs[6,0],qs[6,1]), (qs[2,0],qs[2,1]), forward_color, thickness, cv2.LINE_AA)
        cv2.line(img, (qs[2,0],qs[2,1]), (qs[3,0],qs[3,1]), forward_color, thickness, cv2.LINE_AA)
        cv2.line(img, (qs[3,0],qs[3,1]), (qs[6,0],qs[6,1]), forward_color, thickness, cv2.LINE_AA)
        cv2.line(img, (qs[2,0],qs[2,1]), (qs[7,0],qs[7,1]), forward_color, thickness, cv2.LINE_AA)

    return img

def _quantize_coords(x, y):
    xx = H - int((y - range_y[0]) / vox_height)
    yy = W - int((x - range_x[0]) / vox_width)
    return xx, yy

def  draw_polygons(image, polygons,color=(255,255,255), thickness=1, darken=1):

    img = image.copy() * darken
    for polygon in polygons:
        tup0, tup1, tup2, tup3 = [_quantize_coords(*tup) for tup in polygon]
        cv2.line(img, tup0, tup1, color, thickness, cv2.LINE_AA)
        cv2.line(img, tup1, tup2, color, thickness, cv2.LINE_AA)
        cv2.line(img, tup2, tup3, color, thickness, cv2.LINE_AA)
        cv2.line(img, tup3, tup0, color, thickness, cv2.LINE_AA)
    return img

def draw_rects(image, rects, color=(255,255,255), thickness=1, darken=1):

    img = image.copy() * darken
    for rect in rects:
        tup0,tup1 = [_quantize_coords(*tup) for tup in list(zip(rect[0::2], rect[1::2]))]
        cv2.rectangle(img, tup0, tup1, color, thickness, cv2.LINE_AA)
    return img

def load_kitti_calib(calib_file):
    """
    load projection matrix
    """
    with open(calib_file) as fi:
        lines = fi.readlines()
        assert (len(lines) == 8)

    obj = lines[0].strip().split(' ')[1:]
    P0 = np.array(obj, dtype=np.float32)
    obj = lines[1].strip().split(' ')[1:]
    P1 = np.array(obj, dtype=np.float32)
    obj = lines[2].strip().split(' ')[1:]
    P2 = np.array(obj, dtype=np.float32)
    obj = lines[3].strip().split(' ')[1:]
    P3 = np.array(obj, dtype=np.float32)
    obj = lines[4].strip().split(' ')[1:]
    R0 = np.array(obj, dtype=np.float32)
    obj = lines[5].strip().split(' ')[1:]
    Tr_velo_to_cam = np.array(obj, dtype=np.float32)
    obj = lines[6].strip().split(' ')[1:]
    Tr_imu_to_velo = np.array(obj, dtype=np.float32)

    return {'P2': P2.reshape(3, 4),
            'R0': R0.reshape(3, 3),
            'Tr_velo2cam': Tr_velo_to_cam.reshape(3, 4)}

def angle_in_limit(angle):
    # To limit the angle in -pi/2 - pi/2
    limit_degree = 5
    while angle >= np.pi / 2:
        angle -= np.pi
    while angle < -np.pi / 2:
        angle += np.pi
    if abs(angle + np.pi / 2) < limit_degree / 180 * np.pi:
        angle = np.pi / 2
    return angle

def box3d_cam_to_velo(box3d, Tr):

    def project_cam2velo(cam, Tr):
        T = np.zeros([4, 4], dtype=np.float32)
        T[:3, :] = Tr
        T[3, 3] = 1
        T_inv = np.linalg.inv(T)
        lidar_loc_ = np.dot(T_inv, cam)
        lidar_loc = lidar_loc_[:3]
        return lidar_loc.reshape(1, 3)

    def ry_to_rz(ry):
        angle = -ry - np.pi / 2

        if angle >= np.pi:
            angle -= np.pi
        if angle < -np.pi:
            angle = 2*np.pi + angle

        return angle

    h,w,l,tx,ty,tz,ry = [float(i) for i in box3d]
    cam = np.ones([4, 1])
    cam[0] = tx
    cam[1] = ty
    cam[2] = tz
    t_lidar = project_cam2velo(cam, Tr)

    Box = np.array([[-l / 2, -l / 2, l / 2, l / 2, -l / 2, -l / 2, l / 2, l / 2],
                    [w / 2, -w / 2, -w / 2, w / 2, w / 2, -w / 2, -w / 2, w / 2],
                    [0, 0, 0, 0, h, h, h, h]])

    rz = ry_to_rz(ry)

    rotMat = np.array([
        [np.cos(rz), -np.sin(rz), 0.0],
        [np.sin(rz), np.cos(rz), 0.0],
        [0.0, 0.0, 1.0]])

    velo_box = np.dot(rotMat, Box)

    cornerPosInVelo = velo_box + np.tile(t_lidar, (8, 1)).T

    box3d_corner = cornerPosInVelo.transpose()

    return box3d_corner.astype(np.float32)

def anchors_center_to_corner(anchors):
    N = anchors.shape[0]
    anchor_corner = np.zeros((N, 4, 2))
    for i in range(N):
        anchor = anchors[i]
        translation = anchor[0:3]
        h, w, l = anchor[3:6]
        rz = anchor[-1]
        Box = np.array([
            [-l / 2, -l / 2, l / 2, l / 2], \
            [w / 2, -w / 2, -w / 2, w / 2]])
        # re-create 3D bounding box in velodyne coordinate system
        rotMat = np.array([
            [np.cos(rz), -np.sin(rz)],
            [np.sin(rz), np.cos(rz)]])
        velo_box = np.dot(rotMat, Box)
        cornerPosInVelo = velo_box + np.tile(translation[:2], (4, 1)).T
        box2d = cornerPosInVelo.transpose()
        anchor_corner[i] = box2d
    return anchor_corner


def corner_to_standup_box2d_batch(boxes_corner):
    # (N, 4, 2) -> (N, 4) x1, y1, x2, y2
    N = boxes_corner.shape[0]
    standup_boxes2d = np.zeros((N, 4))
    standup_boxes2d[:, 0] = np.min(boxes_corner[:, :, 0], axis=1)
    standup_boxes2d[:, 1] = np.min(boxes_corner[:, :, 1], axis=1)
    standup_boxes2d[:, 2] = np.max(boxes_corner[:, :, 0], axis=1)
    standup_boxes2d[:, 3] = np.max(boxes_corner[:, :, 1], axis=1)
    return standup_boxes2d

def box3d_corner_to_center_batch(box3d_corner):
    # (N, 8, 3) -> (N, 7)
    assert box3d_corner.ndim == 3
    batch_size = box3d_corner.shape[0]

    xyz = np.mean(box3d_corner[:, :4, :], axis=1)

    h = abs(np.mean(box3d_corner[:, 4:, 2] - box3d_corner[:, :4, 2], axis=1, keepdims=True))

    w = (np.sqrt(np.sum((box3d_corner[:, 0, [0, 1]] - box3d_corner[:, 1, [0, 1]]) ** 2, axis=1, keepdims=True)) +
         np.sqrt(np.sum((box3d_corner[:, 2, [0, 1]] - box3d_corner[:, 3, [0, 1]]) ** 2, axis=1, keepdims=True)) +
         np.sqrt(np.sum((box3d_corner[:, 4, [0, 1]] - box3d_corner[:, 5, [0, 1]]) ** 2, axis=1, keepdims=True)) +
         np.sqrt(np.sum((box3d_corner[:, 6, [0, 1]] - box3d_corner[:, 7, [0, 1]]) ** 2, axis=1, keepdims=True))) / 4

    l = (np.sqrt(np.sum((box3d_corner[:, 0, [0, 1]] - box3d_corner[:, 3, [0, 1]]) ** 2, axis=1, keepdims=True)) +
         np.sqrt(np.sum((box3d_corner[:, 1, [0, 1]] - box3d_corner[:, 2, [0, 1]]) ** 2, axis=1, keepdims=True)) +
         np.sqrt(np.sum((box3d_corner[:, 4, [0, 1]] - box3d_corner[:, 7, [0, 1]]) ** 2, axis=1, keepdims=True)) +
         np.sqrt(np.sum((box3d_corner[:, 5, [0, 1]] - box3d_corner[:, 6, [0, 1]]) ** 2, axis=1, keepdims=True))) / 4

    theta = (np.arctan2(box3d_corner[:, 2, 1] - box3d_corner[:, 1, 1],
                        box3d_corner[:, 2, 0] - box3d_corner[:, 1, 0]) +
             np.arctan2(box3d_corner[:, 3, 1] - box3d_corner[:, 0, 1],
                        box3d_corner[:, 3, 0] - box3d_corner[:, 0, 0]) +
             np.arctan2(box3d_corner[:, 2, 0] - box3d_corner[:, 3, 0],
                        box3d_corner[:, 3, 1] - box3d_corner[:, 2, 1]) +
             np.arctan2(box3d_corner[:, 1, 0] - box3d_corner[:, 0, 0],
                        box3d_corner[:, 0, 1] - box3d_corner[:, 1, 1]))[:, np.newaxis] / 4

    return np.concatenate([xyz, h, w, l, theta], axis=1).reshape(batch_size, 7)

'''
def get_anchor3d(anchors):
    num = anchors.shape[0]
    anchors3d = np.zeros((num,8,3))
    anchors3d[:, :4, :2] = anchors
    anchors3d[:, :, 2] = cfg.z_a
    anchors3d[:, 4:, :2] = anchors
    anchors3d[:, 4:, 2] = cfg.z_a + cfg.h_a
    return anchors3d
'''

def load_kitti_label(label_file, Tr):

    with open(label_file,'r') as f:
        lines = f.readlines()

    gt_boxes3d_corner = []

    num_obj = len(lines)

    for j in range(num_obj):
        obj = lines[j].strip().split(' ')

        obj_class = obj[0].strip()
        if obj_class not in classes:
            continue

        box3d_corner = box3d_cam_to_velo(obj[8:], Tr)

        gt_boxes3d_corner.append(box3d_corner)

    gt_boxes3d_corner = np.array(gt_boxes3d_corner).reshape(-1,8,3)

    return gt_boxes3d_corner



