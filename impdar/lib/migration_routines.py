#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""

Migration routines for ImpDAR

These are mostly based on older scripts in SeisUnix:
https://github.com/JohnWStockwellJr/SeisUnix/wiki
Options are:
    Kirchhoff (diffraction summation)
    Stolt (frequency wavenumber, constant velocity)
    Gazdag (phase shift, either constant or depth-varying velocity)


Author:
Benjamin Hills
benjaminhhills@gmail.com
University of Washington
Earth and Space Sciences

Mar 12 2019

"""

import numpy as np
import time
from scipy import sparse
from scipy.interpolate import griddata, interp2d, interp1d

# -----------------------------------------------------------------------------

def migrationKirchhoff(dat,vel=1.69e8,vel_fn=None,nearfield=False):
    """

    Kirchhoff Migration (Berkhout 1980; Schneider 1978; Berryhill 1979)

    This migration method uses an integral solution to the scalar wave equation Yilmaz (2001) eqn 4.5.
    The algorithm cycles through all every sample in each trace, creating a hypothetical diffraciton
    hyperbola for that location,
        t(x)^2 = t(0)^2 + (2x/v)^2
    To migrate, we integrate the power along that hyperbola and assign the solution to the apex point.
    There are two terms in the integral solution, Yilmaz (2001) eqn 4.5, a far-field term and a
    near-field term. Most algorithms ignor the near-field term because it is small.

    Parameters
    ---------
    dat: data as a dictionary in the ImpDAR format
    vel: wave velocity, default is for ice
    nearfield: boolean to indicate whether or not to use the nearfield term in summation

    Output
    ---------
    dat.data: migrated data

    """

    print('Kirchhoff Migration (diffraction summation) of %.0fx%.0f matrix'%(dat.tnum,dat.snum))
    # check that the arrays are compatible
    if np.size(dat.data,1) != dat.tnum or np.size(dat.data,0) != dat.snum:
        raise ValueError('The input array must be of size (tnum,snum)')
    # start the timer
    start = time.time()
    # Calculate the time derivative of the input data
    gradD = np.gradient(dat.data,dat.travel_time/1e6,axis=0)
    # Create an empty array to fill with migrated data
    migdata = np.zeros_like(dat.data)
    # Loop through all traces
    for xi in range(dat.tnum):
        print('Migrating trace number:',xi)
        # get the trace distance
        x = dat.dist[xi]
        # Loop through all samples
        for ti in range(dat.snum):
            # get the sample time
            t = dat.travel_time[ti]/1e6
            # convert to depth
            z = vel*t/2.
            # get the radial distances between input point and output point
            rs = np.sqrt((dat.dist-x)**2.+z**2.)
            # find the cosine of the angle of the tangent line, correct for obliquity factor
            with np.errstate(invalid='ignore'):
                costheta = z/rs
            # get the exact indices from the array (closest to rs)
            Didx = [np.argmin(abs(dat.travel_time/1e6-2.*r/vel)) for r in rs]
            # integrate the farfield term
            gradDhyp = np.array([gradD[Didx[i],i] for i in range(len(Didx))])
            gradDhyp[2.*rs/vel>max(dat.travel_time/1e6)] = 0.    # zero points that are outside of the domain
            integral = np.nansum(gradDhyp*costheta/vel)  # TODO: Yilmaz eqn 4.5 has an extra r in this weight factor???
            # integrate the nearfield term
            if nearfield == True:
                Dhyp = np.array([dat.data[Didx[i],i] for i in range(len(Didx))])
                Dhyp[2.*rs/vel>max(dat.travel_time/1e6)] = 0.    # zero points that are outside of the domain
                integral += np.nansum(Dhyp*costheta/rs**2.)
            # sum the integrals and output
            migdata[ti,xi] = 1./(2.*np.pi)*integral
    dat.data = migdata.copy()
    # print the total time
    print('Kirchhoff Migration of %.0fx%.0f matrix complete in %.2f seconds'
          %(dat.tnum,dat.snum,time.time()-start))
    return dat

# -----------------------------------------------------------------------------

def migrationStolt(dat,vel=1.68e8,vel_fn=None,nearfield=False):
    """

    Stolt Migration (Stolt, 1978, Geophysics)

    This is by far the fastest migration method. It is a simple transformation from
    frequency-wavenumber (FKx) to wavenumber-wavenumber (KzKx) space.

    Parameters
    ---------
    dat: data as a dictionary in the ImpDAR format
    vel: wave velocity, default is for ice

    Output
    ---------
    dat.data: migrated data

    """

    print('Stolt Migration (f-k migration) of %.0fx%.0f matrix'%(dat.tnum,dat.snum))
    # check that the arrays are compatible
    if np.size(dat.data,1) != dat.tnum or np.size(dat.data,0) != dat.snum:
        raise ValueError('The input array must be of size (tnum,snum)')
    # save the start time
    start = time.time()
    # pad the array with zeros up to the next power of 2 for discrete fft
    nt = 2**(np.ceil(np.log(dat.snum)/np.log(2))).astype(int)
    nx = 2**(np.ceil(np.log(dat.tnum)/np.log(2))).astype(int)
    # 2D Forward Fourier Transform to get data in frequency-wavenumber space, FK = D(kx,z=0,ws)
    FK = np.fft.fft2(dat.data,(nt,nx))
    # get the temporal frequencies
    ws = 2.*np.pi*np.fft.fftfreq(nt, d=dat.dt)
    # get the horizontal wavenumbers
    kx = 2.*np.pi*np.fft.fftfreq(nx, d=np.mean(dat.trace_int))
    # interpolate from frequency (ws) into wavenumber (kz)
    interp_real = interp2d(kx,ws,FK.real)
    interp_imag = interp2d(kx,ws,FK.imag)
    # interpolation will move from frequency-wavenumber to wavenumber-wavenumber, KK = D(kx,kz,t=0)
    KK = np.zeros_like(FK)
    print('Interpolating from temporal frequency (ws) to vertical wavenumber (kz):')
    # for all temporal frequencies
    for zj in range(nt):
        kzj = ws[zj]*2./vel
        if zj%100 == 0:
            print('Interpolating',int(ws[zj]/1e6/2/np.pi),'MHz')
        # for all horizontal wavenumbers
        for xi in range(len(kx)):
            kxi = kx[xi]
            # migration conversion to wavenumber (Yilmaz equation C.53)
            wsj = vel/2.*np.sqrt(kzj**2.+kxi**2.)
            # get the interpolated FFT values, real and imaginary, S(kx,kz,t=0)
            KK[zj,xi] = interp_real(kxi,wsj) + 1j*interp_imag(kxi,wsj)
    # all vertical wavenumbers
    kz = ws*2./vel
    # grid wavenumbers for scaling calculation
    kX,kZ = np.meshgrid(kx,kz)
    # scaling for obliquity factor (Yilmaz equation C.56)
    with np.errstate(invalid='ignore'):
        scaling = kZ/np.sqrt(kX**2.+kZ**2.)
    KK *= scaling
    # the DC frequency should be 0.
    KK[0,0] = 0.+0j
    # 2D Inverse Fourier Transform to get back to distance spce, D(x,z,t=0)
    dat.data = np.real(np.fft.ifft2(KK))
    # Cut array to input matrix dimensions
    dat.data = dat.data[:dat.snum,:dat.tnum]
    # print the total time
    print('Stolt Migration of %.0fx%.0f matrix complete in %.2f seconds'
          %(dat.tnum,dat.snum,time.time()-start))
    return dat

# -----------------------------------------------------------------------------

def migrationPhaseShift(dat,vel=1.69e8,vel_fn=None,nearfield=False):
    """

    Phase-Shift Migration
    case with velocity, v=constant (Gazdag 1978, Geophysics)
    case with layered velocities, v(z) (Gazdag 1978, Geophysics)
    case with vertical and lateral velocity variations, v(x,z) (Ristow and Ruhl 1994, Geophysics)

    Phase-shifting migration for constant, layered, and laterally varying velocity structures.
    This method works down from the surface, using the imaging principle
    (i.e. summing over all frequencies to get the solution at t=0)
    for the migrated section at each step.

    Parameters
    ---------
    dat: data as a dictionary in the ImpDAR format
    vel: v(x,z)
        Up to 2-D array with three columns for velocities (m/s), and z/x (m).
        Array structure is velocities in first column, z location in second, x location in third.
        If uniform velocity (i.e. vel=constant) input constant
        If layered velocity (i.e. vel=v(z)) input array with shape (#vel-points, 2) (i.e. no x-values)
    vel_fn: filename for layered velocity input

    Output
    ---------
    dat.data: migrated data

    **
    The foundation of this script was taken from two places:
    Matlab code written by Andreas Tzanis, Dept. of Geophysics, University of Athens (2005)
    Seis Unix script sumigffd.c, Credits: CWP Baoniu Han, July 21th, 1997
    **

    """

    print('Phase-Shift Migration of %.0fx%.0f matrix'%(dat.tnum,dat.snum))
    # check that the arrays are compatible
    if np.size(dat.data,1) != dat.tnum or np.size(dat.data,0) != dat.snum:
        raise ValueError('The input array must be of size (tnum,snum)')
    # save the start time
    start = time.time()
    # pad the array with zeros up to the next power of 2 for discrete fft
    nt = 2**(np.ceil(np.log(dat.snum)/np.log(2))).astype(int)
    # get frequencies and wavenumbers
    kx = 2.*np.pi*np.fft.fftfreq(dat.tnum,d=np.mean(dat.trace_int))
    ws = 2.*np.pi*np.fft.fftfreq(nt,d=dat.dt)
    # 2D Forward Fourier Transform to get data in frequency-wavenumber space, FK = D(kx,z=0,ws)
    FK = np.fft.fft2(dat.data,(nt,dat.tnum))
    # Velocity structure from input
    if vel_fn is not None:
        try:
            vel = np.genfromtxt(vel_fn)
            print('Velocities loaded from %s.'%vel_fn)
        except:
            raise TypeError('File %s was given for input velocity array, but cannot be loaded. Please reformat.'%vel_fn)
    vmig = getVelocityProfile(dat,vel)
    # Migration by phase shift, frequency-wavenumber (FKx) to time-wavenumber (TKx)
    TK = phaseShift(dat, vmig, vel, kx, ws, FK)
    # Transform from time-wavenumber (TKx) to time-space (TX) domain to get migrated section
    dat.data = np.fft.ifft(TK).real
    # print the total time
    print('Phase-Shift Migration of %.0fx%.0f matrix complete in %.2f seconds'
          %(dat.tnum,dat.snum,time.time()-start))
    return dat

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------

### Supporting functions

def phaseShift(dat, vmig, vels_in, kx, ws, FK):
    """

    Phase-Shift migration to get from frequency-wavenumber (FKx) space to time-wavenumber (TKx) space.
    This is for either constant or layered velocity v(z).

    Parameters
    ---------
    dat: data as a dictionary in the ImpDAR format
    vmig: migration velocity (m/s)
        can be constant or 1-D or 2-D array
    vels_in: v(x,z)
        Up to 2-D array with three columns for velocities (m/s), and z/x (m).
        Array structure is velocities in first column, z location in second, x location in third.
        If uniform velocity (i.e. vel=constant) input constant
        If layered velocity (i.e. vel=v(z)) input array with shape (#vel-points, 2) (i.e. no x-values)
    kx: horizontal wavenumbers
    ws: temporal frequencies
    FK: 2-D array of the data image in frequency-wavenumber space (FKx)

    Output
    ---------
    TK: 2-D array of the migrated data image in time-wavenumber space (TKx).

    **
    The foundation of this script was taken from Matlab code written by Andreas Tzanis,
    Dept. of Geophysics, University of Athens (2005)
    **

    """

    # initialize the time-wavenumber array to be filled with complex values
    TK = np.zeros((dat.snum,len(kx)))+0j

    # Uniform velocity case, vmig=constant
    if not hasattr(vmig,"__len__"):
        print('Constant velocity %s m/usec'%(vmig/1e6))
        # iterate through all frequencies
        for iw in range(len(ws)):
            w = ws[iw]
            if w == 0.0:
                w = 1e-10/dat.dt
            if iw%100 == 0:
                print('Frequency',int(w/1e6/(2.*np.pi)),'MHz')
            # remove frequencies outside of the domain
            vkx2 = (vmig*kx/2.)**2.
            ik = np.argwhere(vkx2 < w**2.)
            FFK = FK[iw,ik]
            # get the phase for shift
            phase = (-w*dat.dt*np.sqrt(1.0 - vkx2[ik]/w**2.)).real
            cp = np.conj(np.cos(phase)+1j*np.sin(phase))
            # Accumulate output image (time-wavenumber space) summed over all frequencies
            for itau in range(dat.snum):
                 FFK *= cp
                 TK[itau,ik] += FFK

    else:
        # Layered and/or lateral velocity case, vmig=v(x,z)
        if len(vmig) != dat.snum:
            raise ValueError('Interpolated velocity profile is not the length of the number of samples in a trace.')
        if hasattr(vmig[0],"__len__"):
            print('2-D velocity structure, Fourier Finite-Difference Migration')
            # Finite Difference Stencil
            stencil = Sp_Matr(dat.tnum,-2,1,1)
            FFX_last = 0.
        else:
            print('1-D velocity structure, Gazdag Migration')
            print('Velocities (m/s): %.2e',vels_in[:,0])
            print('Depths (m):',vels_in[:,1])
        # iterate through all output travel times
        for itau in range(dat.snum):
            tau = dat.travel_time[itau]/1e6
            if itau%10 == 0:
                print('Time %.2e of %.2e' %(tau,dat.travel_time[-1]/1e6))
            # iterate through all frequencies
            for iw in range(len(ws)):
                w = ws[iw]
                if w == 0.0:
                    w = 1e-10/dat.dt

                # Get foreground and background velocities
                if hasattr(vmig[itau],"__len__"):
                    vbg = np.min(vmig[itau])
                    vfg = vmig[itau]-vbg
                else:
                    vbg = vmig[itau]

                ### Retardation term
                # cosine squared
                coss = 1.0+0j - (0.5*vbg*kx/w)**2.
                # calculate phase for shift
                phase = (-w*dat.dt*np.sqrt(coss)).real
                cshift = np.conj(np.cos(phase)+1j*np.sin(phase))
                FK[iw] *= cshift

                if hasattr(vmig[itau],"__len__"):
                    # inverse fourier tranform to frequency-space domain
                    FFX = np.fft.ifft(FK[iw])

                    ### Thin-lens term (Stoffa et al. 1990)
                    phase2 = (1./vbg - 2./vfg)*w*dat.dt # TODO: I am pretty sure that this is wrong
                    cshift2 = np.cos(phase2) + 1j*np.sin(phase2)
                    FFX *= cshift2

                    ### Diffraction term, Finite Difference operator
                    if itau > 0:
                        FFX = fourierFiniteDiff(dat,vfg,w,FFX,FFX_last,stencil)
                    FFX_last = FFX

                    # Fourier transform back to frequency-wavenumber domain
                    FK[iw] = np.fft.fft(FFX)

                # zero if outside domain
                idx = coss <= (tau/dat.travel_time[-1]/1e6)**2.
                FK[iw,idx] = 0.0 + 0j
                # sum over all frequencies
                TK[itau] += FK[iw]

    # Cut to original array size
    TK = TK[:,:dat.tnum]
    # Normalize for inverse FFT
    TK /= dat.snum
    return TK

# -----------------------------------------------------------------------------

def fourierFiniteDiff(dat, vs, w, FFX, FFX_last, stencil, alpha=0.5,beta=0.25):
    """

    Fourier Finite-Difference operator to correct for diffraction in the phase-shift method.
    This is for variable velocity v(x,z).

    Parameters
    ---------
    dat: data as a dictionary in the ImpDAR format
    vs: 1-D array of migration velocity (m/s)
    w: scalar temporal frequency
    FFX: 2-D array of the data image in frequency-space (FX)
    FFX_last: same as FFX but for the last iteration (i.e. tau-1)
    alpha: coefficient on second order term, default to 0.5 for 45-degree equation
    beta: coefficient on third order term, default to 0.25 for 45-degree equation

    Output
    ---------
    FFX: Updated input term, 2-D array of the data image in frequency-space (FX)

    """

    # Coefficients
    dx = np.mean(dat.trace_int)
    coeff1 = dat.dt*alpha*vs**2./(1j*4.*w*dx**2.)
    coeff2 = -beta*vs**2./(4.*w**2.*dx**2.)

    # Update equation, explicit backward Euler
    FFX = FFX_last + coeff1*(stencil*FFX) + coeff2*(stencil*FFX - stencil*FFX_last)
    return FFX

# -----------------------------------------------------------------------------

# Define a function to write a sparse matrix
def Sp_Matr(N,diag,k1,k2,k3=0,k4=0,nx=0):
    A = sparse.lil_matrix((N, N))           #Function to create a sparse Matrix
    A.setdiag((diag)*np.ones(N))            #Set the diagonal
    A.setdiag((k1)*np.ones(N-1),k=1)        #Set the first upward off-diagonal.
    A.setdiag((k2)*np.ones(N-1),k=-1)       #Set the first downward off-diagonal
    A.setdiag((k3)*np.ones(N-nx),k=nx)      #Set for diffusion from above node
    A.setdiag((k4)*np.ones(N-nx),k=-nx)     #Set for diffusion from below node
    # Set Dirichlet boundary conditions
    A[0,0] = 1
    A[0,1:] = 0
    A[-1,-1] = 1
    A[-1,:-1] = 1
    return A

# -----------------------------------------------------------------------------

def getVelocityProfile(dat,vels_in):
    """

    Map the layered velocity structure into the shape of the data.

    Parameters
    ---------
    dat: data as a dictionary in the ImpDAR format
    vels_in: v(x,z)
        Up to 2-D array with three columns for velocities (m/s), and z/x (m).
        Array structure is velocities in first column, z location in second, x location in third.
        If uniform velocity (i.e. vel=constant) input constant
        If layered velocity (i.e. vel=v(z)) input array with shape (#vel-points, 2) (i.e. no x-values)

    Output
    ---------
    vmig: 2-D array of migration velocities (m/s), shape is (#traces, #samples).
        If constant input velocity, output is constant.
        If only z-component in input velocity array, output is v(z)

    """

    # return the input value if it is a constant
    if not hasattr(vels_in,"__len__"):
        return vels_in

    start = time.time()
    print('Interpolating the velocity profile.')

    nlay,dimension = np.shape(vels_in)
    vel_v = vels_in[:,0]
    vel_z = vels_in[:,1]

    twtt = dat.travel_time.copy()/1e6
    ### Layered Velocity
    if nlay > 1 and dimension == 2:
        zs = np.max(vel_v)/2.*twtt      # depth array for maximum possible penetration
        zs[0] = twtt[0]*vel_v[0]/2.
        # If an input point is closest to a boundary push it to the boundary
        if vel_z[0] > np.nanmin(zs):
            vel_v = np.insert(vel_v,0,vel_v[np.argmin(vel_z)])
            vel_z = np.insert(vel_z,0,np.nanmin(zs))
        if vel_z[-1] < np.nanmax(zs):
            vel_v = np.append(vel_v,vel_v[np.argmax(vel_z)])
            vel_z = np.append(vel_z,np.nanmax(zs))
        # Compute times from input velocity/location array (vels_in)
        vel_t = 2.*vel_z/vel_v
        # Interpolate to get t(z) for maximum penetration depth array
        tinterp = interp1d(vel_z,vel_t)
        tofz = tinterp(zs)
        # Compute z(t) from monotonically increasing t
        zinterp = interp1d(tofz,zs)
        zoft = zinterp(twtt)
        if twtt[-1] > tofz[-1]:
            raise ValueError('Two-way travel time array extends outside of interpolation range')
        # Compute vmig(t) from z(t)
        vmig = 2.*np.gradient(zoft,twtt)

    ### Lateral Velocity Variations TODO: I need to check this more rigorously too.
    elif nlay > 1 and dimension == 3:
        vel_x = vels_in[:,2]    # Input velocities
        # Depth array for largest penetration range
        zs = np.linspace(np.min(vel_v)*twtt[0],
                 np.max(vel_v)*twtt[-1],
                 dat.snum)/2.
        # Use nearest neighbor interpolation to grid the input points onto a mesh
        if all(dat.dist == 0):
            raise ValueError('The distance vector was never set.')
        XS,ZS = np.meshgrid(dat.dist,zs)
        VS = griddata(np.transpose([vel_x,vel_z]),vel_v,np.transpose([XS.flatten(),ZS.flatten()]),method='nearest')
        VS = np.reshape(VS,np.shape(XS))

        # convert velocities into travel_time space for all traces
        vmig = np.zeros_like(VS)
        for i in range(dat.tnum):
            vel_z = ZS[:,i]
            vel_v = VS[:,i]
            # Compute times from input velocity/location array (vels_in)
            vel_t = 2*np.array([np.trapz(1./vel_v[:j],vel_z[:j]) for j in range(dat.snum)])
            # Interpolate to get t(z) for maximum penetration depth array
            tinterp = interp1d(ZS[:,i],vel_t)
            tofz = tinterp(zs)
            # Compute z(t) from monotonically increasing t
            zinterp = interp1d(tofz,zs)
            zoft = zinterp(twtt)
            if twtt[-1] > tofz[-1]:
                raise ValueError('Two-way travel time array extends outside of interpolation range')
            # Compute vmig(t) from z(t)
            vmig[:,i] = 2.*np.gradient(zoft,twtt)

    print('Velocity profile finished in %.2f seconds.'%(time.time()-start))

    return vmig